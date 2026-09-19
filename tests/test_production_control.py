import json
import time

import pytest

from production_control import ProductionControlPlane


@pytest.fixture()
def control(tmp_path, monkeypatch):
    monkeypatch.setenv("AURIC_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "AURIC_API_KEYS_JSON",
        json.dumps({
            "viewer-secret": {"name": "viewer-user", "role": "viewer"},
            "trader-secret": {"name": "trader-user", "role": "trader"},
            "admin-secret": {"name": "admin-user", "role": "admin"},
        }),
    )
    monkeypatch.setenv("NEWS_GUARD_ENABLED", "true")
    monkeypatch.setenv("NEWS_GUARD_MIN_IMPACT", "high")
    return ProductionControlPlane(str(tmp_path / "control.db"))


def test_rbac_roles(control):
    viewer = control.authenticate("viewer-secret")
    trader = control.authenticate("trader-secret")
    admin = control.authenticate("admin-secret")
    anon = control.authenticate(None)

    assert control.allowed(viewer, "viewer")
    assert not control.allowed(viewer, "trader")
    assert control.allowed(trader, "trader")
    assert not control.allowed(trader, "admin")
    assert control.allowed(admin, "admin")
    assert not control.allowed(anon, "viewer")


def test_execution_stage_and_persistent_halt(control):
    assert control.execution_stage() == "paper"
    control.set_execution_stage("assisted")
    assert control.execution_stage() == "assisted"

    control.halt("operator kill")
    assert control.is_halted()
    allowed, reason = control.trade_gate("XAUUSD", "live")
    assert not allowed
    assert "operator kill" in reason

    control.resume()
    assert not control.is_halted()


def test_news_blackout_blocks_live_not_paper(control):
    now = int(time.time() * 1000)
    event_id = control.add_news(
        title="High impact macro release",
        impact="high",
        start_ms=now - 1000,
        end_ms=now + 60_000,
        symbols=["XAUUSD"],
        source="test",
    )
    control.set_execution_stage("assisted")

    live_ok, live_reason = control.trade_gate("XAUUSD", "live")
    paper_ok, _ = control.trade_gate("XAUUSD", "paper")
    eur_ok, _ = control.trade_gate("EURUSD", "live")

    assert not live_ok
    assert "News blackout" in live_reason
    assert paper_ok
    assert eur_ok

    assert control.set_news_enabled(event_id, False)
    live_ok, _ = control.trade_gate("XAUUSD", "live")
    assert live_ok


def test_auto_stage_required_for_autonomous_live(control):
    control.set_execution_stage("assisted")
    allowed, _ = control.trade_gate("XAUUSD", "live", autonomous=True)
    assert not allowed
    control.set_execution_stage("auto")
    allowed, _ = control.trade_gate("XAUUSD", "live", autonomous=True)
    assert allowed


def test_portfolio_policy_blocks_exposure(control, monkeypatch):
    monkeypatch.setenv("MAX_OPEN_POSITIONS", "2")
    monkeypatch.setenv("MAX_TOTAL_LOTS", "1.0")
    monkeypatch.setenv("MAX_SYMBOL_LOTS", "0.6")
    monkeypatch.setenv("MIN_MARGIN_LEVEL_PCT", "150")
    monkeypatch.setenv("MAX_MARGIN_USAGE_PCT", "35")

    ok, reasons = control.portfolio_gate(
        requested_lots=0.2,
        symbol_lots=0.5,
        total_lots=0.9,
        open_positions=2,
        margin_level=120,
        margin_used=4000,
        equity=10_000,
    )
    assert not ok
    assert len(reasons) >= 4


def test_rate_limit(control):
    control.read_rpm = 2
    assert control.rate_allowed("user", "GET", "/api/quote")[0]
    assert control.rate_allowed("user", "GET", "/api/quote")[0]
    allowed, retry = control.rate_allowed("user", "GET", "/api/quote")
    assert not allowed
    assert retry >= 1


def test_audit_and_reconciliation(control):
    principal = control.authenticate("admin-secret")
    control.audit(
        request_id="abc",
        principal=principal,
        action="POST",
        path="/api/system/stage",
        status=200,
        detail={"stage": "paper"},
    )
    rows = control.audit_rows(10)
    assert rows[0]["actor"] == "admin-user"
    assert rows[0]["path"] == "/api/system/stage"

    control.record_reconciliation("ok", {"livePositions": 1})
    last = control.last_reconciliation()
    assert last is not None
    assert last["status"] == "ok"
    assert last["summary"]["livePositions"] == 1

import json
import time

import pytest

from production_core import (
    AuditLog,
    BlackoutGuard,
    ExecutionPolicy,
    OperatorAuth,
    ReconciliationState,
    TokenBucketLimiter,
    production_readiness,
)


def test_execution_policy_stages(monkeypatch):
    monkeypatch.setenv("AURIC_EXECUTION_STAGE", "paper")
    p = ExecutionPolicy()
    assert p.paper_allowed is True
    assert p.live_manual_allowed is False
    assert p.auto_live_allowed is False
    assert ExecutionPolicy("assisted").live_manual_allowed is True
    assert ExecutionPolicy("auto").auto_live_allowed is True
    assert ExecutionPolicy("shadow").paper_allowed is False


def test_operator_auth_roundtrip(monkeypatch):
    monkeypatch.setenv("AURIC_AUTH_SECRET", "x" * 32)
    monkeypatch.setenv("AURIC_OPERATOR_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.setenv("AURIC_OPERATOR_USERNAME", "operator")
    auth = OperatorAuth()
    token = auth.issue("operator", "correct-horse-battery-staple")
    claims = auth.verify(token)
    assert claims["sub"] == "operator"
    assert claims["role"] == "operator"
    with pytest.raises(PermissionError):
        auth.verify(token + "broken")


def test_rate_limiter():
    limiter = TokenBucketLimiter(capacity=2, refill_per_sec=0.01)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False


def test_audit_log_roundtrip(tmp_path):
    audit = AuditLog(str(tmp_path / "audit.db"))
    audit.write(actor="operator", action="POST", resource="/api/orders", outcome="200",
                request_id="r1", remote="127.0.0.1", details={"symbol": "XAUUSD"})
    rows = audit.recent()
    assert rows[0]["actor"] == "operator"
    assert rows[0]["details"]["symbol"] == "XAUUSD"


def test_blackout_guard_blocks_matching_symbol(tmp_path, monkeypatch):
    now = int(time.time())
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"events": [{
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "title": "CPI", "symbols": ["XAUUSD"], "importance": "high",
        "minutes_before": 10, "minutes_after": 10
    }]}))
    monkeypatch.setenv("ECONOMIC_CALENDAR_FILE", str(path))
    guard = BlackoutGuard()
    assert guard.check("XAUUSD")["allowed"] is False
    assert guard.check("BTCUSD")["allowed"] is True


def test_readiness_fails_closed_for_production_live(monkeypatch):
    monkeypatch.setenv("AURIC_REQUIRE_AUTH", "true")
    monkeypatch.delenv("AURIC_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AURIC_OPERATOR_PASSWORD", raising=False)
    auth = OperatorAuth()
    recon = ReconciliationState()
    payload = production_readiness(
        env_name="production",
        policy=ExecutionPolicy("assisted"),
        auth=auth,
        live_enabled=True,
        auto_live_enabled=False,
        live_api_key="",
        mt5_connected=False,
        reconciliation=recon,
    )
    assert payload["ready"] is False
    assert any(not check["ok"] for check in payload["checks"])

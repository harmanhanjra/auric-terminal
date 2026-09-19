"""API tests. Run against the FastAPI app with the demo/web source (no MT5)."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_candles(n=520):
    import math
    out, p, seed = [], 4950.0, 144021
    for i in range(n):
        seed = (seed * 1664525 + 1013904223) % 4294967296
        r = seed / 4294967296 - 0.47
        o = p
        c = o + r * 12 + math.sin(i / 17) * 0.8
        h = max(o, c) + 1.2
        l = min(o, c) - 1.1
        out.append({"time": i, "open": o, "high": h, "low": l,
                    "close": c, "volume": 100 + i % 31})
        p = c
    return out


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import server
    from execution_v2 import ExecutionLedger, PaperBroker
    from production_control import ProductionControlPlane
    tmp = tmp_path_factory.mktemp("db")
    db = str(tmp / "test.db")
    server.journal = server.Journal(db)
    server.execution_ledger = ExecutionLedger(db)
    server.paper_broker = PaperBroker()
    server.control = ProductionControlPlane(db)
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="module")
def candles():
    return make_candles()


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Auric" in r.text


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["liveTrading"] is False
    assert body["autoLiveTrading"] is False


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") in ("DENY", "SAMEORIGIN")
    assert r.headers.get("referrer-policy") is not None


def test_quote(client):
    r = client.get("/api/quote")
    assert r.status_code == 200
    body = r.json()
    assert "price" in body
    assert "source" in body


def test_strategies(client):
    r = client.get("/api/strategies")
    assert r.status_code == 200
    body = r.json()
    assert len(body["strategies"]) == 19
    assert "positionSizing" in body


def test_backtest_valid(client, candles):
    r = client.post("/api/backtest", json={
        "candles": candles, "strategy": "ema144_pullback", "params": {},
        "initial": 10000, "risk_pct": 1, "sizer": "fixed_fractional",
        "spread": 0.18})
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body and "equity_curve" in body


def test_backtest_unknown_strategy(client, candles):
    r = client.post("/api/backtest", json={
        "candles": candles, "strategy": "nope", "params": {}, "initial": 10000,
        "risk_pct": 1, "sizer": "fixed_fractional", "spread": 0.18})
    assert r.status_code == 422


def test_backtest_too_few_candles(client):
    r = client.post("/api/backtest", json={
        "candles": make_candles(100), "strategy": "ema144_pullback",
        "params": {}, "initial": 10000, "risk_pct": 1,
        "sizer": "fixed_fractional", "spread": 0.18})
    assert r.status_code == 422


def test_backtest_malformed_candles(client):
    bad = [{"open": "x", "high": 1, "low": 1, "close": 1}] * 300
    r = client.post("/api/backtest", json={
        "candles": bad, "strategy": "ema144_pullback", "params": {},
        "initial": 10000, "risk_pct": 1, "sizer": "fixed_fractional",
        "spread": 0.18})
    assert r.status_code == 422


def test_optimize_bounded(client, candles):
    r = client.post("/api/optimize", json={
        "candles": candles, "strategy": "bb_rsi", "grid": {"p": [1, 2, 3, 4]}})
    assert r.status_code == 200
    assert len(r.json()["runs"]) == 4


def test_optimize_too_large_grid(client, candles):
    grid = {f"k{i}": [1, 2, 3, 4] for i in range(8)}
    r = client.post("/api/optimize", json={
        "candles": candles, "strategy": "bb_rsi", "grid": grid})
    assert r.status_code == 422


def test_monte_carlo(client):
    r = client.post("/api/monte-carlo", json={
        "trades": [{"pnl": 120}, {"pnl": -40}, {"pnl": 55}],
        "runs": 1000, "initial": 10000})
    assert r.status_code == 200
    assert r.json()["runs"] == 1000


def test_monte_carlo_none_pnl(client):
    r = client.post("/api/monte-carlo", json={
        "trades": [{"pnl": None}, {"pnl": 40}, {}, {"pnl": -20}],
        "runs": 100, "initial": 10000})
    assert r.status_code == 200
    assert r.json()["risk_of_ruin_pct"] >= 0


def test_order_paper(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "latest", {
        "XAUUSD": {"bid": 5024.36, "ask": 5024.54, "spread": 0.18, "source": "test"}
    })
    r = client.post("/api/orders", json={
        "side": "buy", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "paper", "client_order_id": "test-order-0001"})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["mode"] == "paper"
    positions = client.get("/api/positions?mode=paper").json()["positions"]
    assert any(p["symbol"] == "XAUUSD" and p["mode"] == "paper" for p in positions)


def test_order_live_disabled(client):
    r = client.post("/api/orders", json={
        "side": "sell", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "live", "client_order_id": "test-order-0002"})
    assert r.status_code == 403


def test_live_order_requires_execution_key(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "LIVE_ENABLED", True)
    monkeypatch.setattr(server, "LIVE_API_KEY", "test-secret-key")
    r = client.post("/api/orders", json={
        "side": "sell", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "live", "client_order_id": "test-order-auth"})
    assert r.status_code == 401


def test_live_execution_fails_closed_without_configured_key(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "LIVE_ENABLED", True)
    monkeypatch.setattr(server, "LIVE_API_KEY", "")
    r = client.post("/api/orders", json={
        "side": "sell", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "live", "client_order_id": "test-order-nokey"})
    assert r.status_code == 503


def test_order_lots_over_server_limit(client):
    r = client.post("/api/orders", json={
        "side": "buy", "lots": 999, "stop_loss": None, "take_profit": None,
        "mode": "paper", "client_order_id": "test-order-0003"})
    assert r.status_code == 422


def test_order_bad_client_id(client):
    r = client.post("/api/orders", json={
        "side": "buy", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "paper", "client_order_id": "short"})
    assert r.status_code == 422


def test_engine_disabled_stop(client):
    r = client.post("/api/engine/stop")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    client.post("/api/engine/start")  # restore for other tests


def test_kill_paper(client):
    r = client.post("/api/kill?mode=paper")
    assert r.status_code == 200
    assert r.json()["halted"] is True
    client.post("/api/risk/reset")
    client.post("/api/system/resume")


def test_account_unavailable(client):
    r = client.get("/api/account")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_candles_always_available(client):
    # MT5 is offline in CI. Yahoo may be reachable; otherwise the honest Demo fallback is used.
    r = client.get("/api/candles?interval=M15")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in {"Yahoo", "Demo"}
    assert len(body["values"]) >= 10
    assert all({"open", "high", "low", "close"} <= set(v) for v in body["values"])


def test_journal(client):
    r = client.get("/api/journal?limit=5")
    assert r.status_code == 200
    assert "entries" in r.json()


def test_engine_endpoint(client):
    r = client.get("/api/engine")
    assert r.status_code == 200
    body = r.json()
    for key in ("running", "enabled", "strategy", "timeframe", "status",
                "trades", "config", "risk"):
        assert key in body



def test_risk_preview_symbol_aware(client):
    r = client.post("/api/risk/preview", json={
        "symbol": "XAUUSD", "side": "buy",
        "entry": 5000, "stop": 4990, "target": 5020,
        "risk_amount": 50, "risk_pct": 1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["lots"] == pytest.approx(0.05)
    assert body["riskUsd"] == pytest.approx(50, abs=0.01)
    assert body["rr"] == pytest.approx(2.0)


def test_pending_order_requires_entry(client):
    r = client.post("/api/orders", json={
        "side": "buy", "lots": 0.05, "order_type": "limit",
        "stop_loss": 4990, "take_profit": 5030,
        "mode": "paper", "client_order_id": "pending-no-entry",
    })
    assert r.status_code == 422


def test_durable_duplicate_order_id_rejected(client, monkeypatch):
    import server
    server.risk.halted = False
    monkeypatch.setattr(server, "latest_by_symbol", {
        "XAUUSD": {"symbol": "XAUUSD", "bid": 5000.0, "ask": 5000.18,
                   "spread": 0.18, "source": "test", "timestamp": 1}
    })
    payload = {
        "side": "buy", "lots": 0.01, "order_type": "market",
        "stop_loss": 4990, "take_profit": 5020,
        "mode": "paper", "client_order_id": "duplicate-v2-0001",
    }
    assert client.post("/api/orders", json=payload).status_code == 200
    r = client.post("/api/orders", json=payload)
    assert r.status_code == 409


def test_global_paper_kill_flattens_all(client, monkeypatch):
    import server
    server.risk.halted = False
    monkeypatch.setattr(server, "latest_by_symbol", {
        "XAUUSD": {"symbol": "XAUUSD", "bid": 5000.0, "ask": 5000.18,
                   "spread": 0.18, "source": "test", "timestamp": 1},
        "EURUSD": {"symbol": "EURUSD", "bid": 1.0850, "ask": 1.0851,
                   "spread": 0.0001, "source": "test", "timestamp": 1},
    })
    for symbol, client_id in [("XAUUSD", "kill-xau-v2"), ("EURUSD", "kill-eur-v2")]:
        r = client.post("/api/orders", json={
            "symbol": symbol, "side": "buy", "lots": 0.01, "order_type": "market",
            "mode": "paper", "client_order_id": client_id,
        })
        assert r.status_code == 200
    assert len(client.get("/api/positions?mode=paper").json()["positions"]) >= 2
    killed = client.post("/api/kill?mode=paper").json()
    assert killed["halted"] is True
    assert killed["closed"] >= 2
    assert client.get("/api/positions?mode=paper").json()["positions"] == []
    client.post("/api/risk/reset")



def test_v3_readiness_and_system_status(client):
    ready = client.get("/api/readiness")
    assert ready.status_code == 200
    assert "checks" in ready.json()
    assert ready.json()["production"]["executionStage"] in {"shadow", "paper", "assisted", "auto"}

    status = client.get("/api/system/status")
    assert status.status_code == 200
    body = status.json()
    assert body["version"] == "3.0.0"
    assert "riskPolicy" in body
    assert "circuit" in body


def test_v3_stage_promotion_local_admin(client):
    r = client.post("/api/system/stage", json={"stage": "shadow"})
    assert r.status_code == 200
    assert r.json()["executionStage"] == "shadow"
    r = client.post("/api/system/stage", json={"stage": "paper"})
    assert r.status_code == 200
    assert r.json()["executionStage"] == "paper"


def test_v3_paper_position_management(client, monkeypatch):
    import server
    server.control.resume()
    server.risk.halted = False
    monkeypatch.setattr(server, "latest_by_symbol", {
        "XAUUSD": {"symbol": "XAUUSD", "bid": 5000.0, "ask": 5000.18,
                   "spread": 0.18, "source": "test", "timestamp": 1}
    })
    placed = client.post("/api/orders", json={
        "symbol": "XAUUSD", "side": "buy", "lots": 0.10, "order_type": "market",
        "stop_loss": 4990, "take_profit": 5020,
        "mode": "paper", "client_order_id": "manage-paper-v3",
    })
    assert placed.status_code == 200
    ticket = placed.json()["ticket"]

    protected = client.post(
        f"/api/positions/{ticket}/protect",
        json={"mode": "paper", "breakeven": True},
    )
    assert protected.status_code == 200
    assert protected.json()["position"]["sl"] == pytest.approx(protected.json()["position"]["entry"])

    half = client.post(
        f"/api/positions/{ticket}/close",
        json={"mode": "paper", "lots": 0.05},
    )
    assert half.status_code == 200
    remaining = client.get("/api/positions?mode=paper").json()["positions"]
    row = next(p for p in remaining if p["ticket"] == ticket)
    assert row["lots"] == pytest.approx(0.05)

    closed = client.post(
        f"/api/positions/{ticket}/close",
        json={"mode": "paper"},
    )
    assert closed.status_code == 200
    assert all(p["ticket"] != ticket for p in client.get("/api/positions?mode=paper").json()["positions"])


def test_v3_auth_enforcement(client):
    import server
    from production_control import Principal

    old_required = server.control.auth_required
    old_keys = server.control._keys
    try:
        server.control.auth_required = True
        import hashlib
        server.control._keys = {
            hashlib.sha256(b"viewer-test").hexdigest(): Principal(
                name="viewer", role="viewer", authenticated=True
            ),
            hashlib.sha256(b"admin-test").hexdigest(): Principal(
                name="admin", role="admin", authenticated=True
            ),
        }

        assert client.get("/api/account").status_code == 401
        viewer_headers = {"X-Auric-Auth": "viewer-test"}
        assert client.get("/api/account", headers=viewer_headers).status_code == 200
        assert client.post("/api/system/stage", json={"stage": "paper"}, headers=viewer_headers).status_code == 403

        admin_headers = {"X-Auric-Auth": "admin-test"}
        assert client.post("/api/system/stage", json={"stage": "paper"}, headers=admin_headers).status_code == 200
    finally:
        server.control.auth_required = old_required
        server.control._keys = old_keys

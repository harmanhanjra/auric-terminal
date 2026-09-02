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
    tmp = tmp_path_factory.mktemp("db")
    server.journal = server.Journal(str(tmp / "test.db"))
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


def test_order_paper(client):
    r = client.post("/api/orders", json={
        "side": "buy", "lots": 0.2, "stop_loss": None, "take_profit": None,
        "mode": "paper", "client_order_id": "test-order-0001"})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["mode"] == "paper"


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


def test_account_unavailable(client):
    r = client.get("/api/account")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_candles_unavailable_without_source(client):
    r = client.get("/api/candles?interval=M15")
    assert r.status_code in (502, 503)


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

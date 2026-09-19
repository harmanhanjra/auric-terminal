"""Auric V2 execution-layer tests: deterministic and broker-independent."""
import sqlite3

import pytest

from execution_v2 import (
    ExecutionLedger,
    PaperBroker,
    SymbolSpec,
    fallback_spec,
    normalize_price,
    normalize_volume,
    position_size_for_risk,
    risk_per_lot,
    spread_points,
)


def test_xau_risk_sizing_uses_tick_value():
    spec = fallback_spec("XAUUSD")
    lots = position_size_for_risk(10_000, 0.5, 5000, 4990, spec, 1.0)
    assert lots == pytest.approx(0.05)
    assert risk_per_lot(5000, 4990, spec) == pytest.approx(1000)


def test_eurusd_risk_sizing_is_not_gold_math():
    spec = fallback_spec("EURUSD")
    lots = position_size_for_risk(10_000, 1.0, 1.1000, 1.0980, spec, 2.0)
    assert lots == pytest.approx(0.5)
    assert risk_per_lot(1.1000, 1.0980, spec) == pytest.approx(200)


def test_volume_and_price_normalization():
    spec = SymbolSpec("TEST", 3, 0.001, 0.005, 1, 1, 0.1, 5, 0.1)
    assert normalize_price(12.3471, spec) == pytest.approx(12.345)
    assert normalize_volume(0.37, spec) == pytest.approx(0.3)


def test_spread_points_are_asset_relative():
    xau = fallback_spec("XAUUSD")
    eur = fallback_spec("EURUSD")
    assert spread_points(5000, 5000.18, xau) == pytest.approx(18)
    assert spread_points(1.0850, 1.0851, eur) == pytest.approx(10)


def test_execution_ledger_is_durable(tmp_path):
    path = str(tmp_path / "ledger.db")
    a = ExecutionLedger(path)
    assert a.reserve("same-id", "XAUUSD", "paper", "market", {"x": 1}) is True
    a.complete("same-id", {"accepted": True}, 42)
    b = ExecutionLedger(path)
    assert b.reserve("same-id", "XAUUSD", "paper", "market", {"x": 2}) is False
    row = b.lookup("same-id")
    assert row is not None
    assert row["status"] == "filled"

    # Duplicate reservation must not leave a SQLite writer lock behind.
    other = sqlite3.connect(path, timeout=0.2)
    other.execute("CREATE TABLE IF NOT EXISTS lock_probe(id INTEGER)")
    other.execute("INSERT INTO lock_probe(id) VALUES(1)")
    other.commit()
    other.close()


def test_paper_broker_pending_fill_and_target():
    broker = PaperBroker()
    spec = fallback_spec("XAUUSD")
    result = broker.place(
        symbol="XAUUSD", side="buy", lots=0.1, order_type="limit",
        bid=5000.0, ask=5000.2, entry_price=4999.0,
        stop_loss=4995.0, take_profit=5005.0,
        client_order_id="paper-limit", spec=spec,
    )
    assert result["status"] == "pending"
    assert len(broker.pending()) == 1

    events = broker.on_tick("XAUUSD", 4998.8, 4999.0)
    assert any(e["type"] == "fill" for e in events)
    assert len(broker.positions()) == 1

    events = broker.on_tick("XAUUSD", 5005.1, 5005.3)
    close = next(e for e in events if e["type"] == "close")
    assert close["reason"] == "Target"
    assert close["pnl"] > 0
    assert broker.positions() == []



def test_paper_broker_persists_positions_and_pending(tmp_path):
    path = str(tmp_path / "paper.db")
    spec = fallback_spec("XAUUSD")
    first = PaperBroker(path)
    market = first.place(
        symbol="XAUUSD", side="buy", lots=0.1, order_type="market",
        bid=5000.0, ask=5000.2, entry_price=None,
        stop_loss=4990.0, take_profit=5020.0,
        client_order_id="paper-persist-market", spec=spec,
    )
    pending = first.place(
        symbol="XAUUSD", side="buy", lots=0.1, order_type="limit",
        bid=5000.0, ask=5000.2, entry_price=4995.0,
        stop_loss=4990.0, take_profit=5010.0,
        client_order_id="paper-persist-limit", spec=spec,
    )

    second = PaperBroker(path)
    assert any(p["ticket"] == market["ticket"] for p in second.positions())
    assert any(o["ticket"] == pending["ticket"] for o in second.pending())

    second.protect_position(market["ticket"], breakeven=True)
    third = PaperBroker(path)
    restored = next(p for p in third.positions() if p["ticket"] == market["ticket"])
    assert restored["sl"] == pytest.approx(restored["entry"])

    third.cancel_pending(pending["ticket"])
    fourth = PaperBroker(path)
    assert fourth.pending() == []

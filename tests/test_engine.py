"""Baseline tests for the engine. Deterministic, no network or MT5 required."""
import math

import pytest

from engine import (SIZERS, STRATEGIES, Journal, RiskManager, atr, backtest,
                    indicators, monte_carlo, optimize, position_size, rsi,
                    signal, sma, ema, stdev)


def make_candles(n=520, start=4950.0, seed=144021):
    out, p = [], start
    for i in range(n):
        seed = (seed * 1664525 + 1013904223) % 4294967296
        r = seed / 4294967296 - 0.47
        o = p
        c = o + r * 12 + math.sin(i / 17) * 0.8
        h = max(o, c) + 1.2 + (i % 7) * 0.17
        l = min(o, c) - 1.1 - (i % 5) * 0.15
        out.append({"time": i, "open": o, "high": h, "low": l,
                    "close": c, "volume": 100 + (i % 31) * 8})
        p = c
    return out


@pytest.fixture(scope="module")
def candles():
    return make_candles()


@pytest.fixture(scope="module")
def ind(candles):
    return indicators(candles)


# --- indicators ----------------------------------------------------------

def test_sma_matches_reference():
    v = [1.0, 2.0, 3.0, 4.0, 5.0]
    n = 3
    out = sma(v, n)
    expected = [1.0, 1.5, 2.0, 3.0, 4.0]
    assert len(out) == len(v)
    for got, want in zip(out, expected):
        assert got == pytest.approx(want)


def test_sma_empty():
    assert sma([], 5) == []


def test_ema_length_and_tail(candles):
    e = ema([x["close"] for x in candles], 20)
    assert len(e) == len(candles)
    assert e[-1] == pytest.approx(
        (sum(x["close"] for x in candles[-20:]) / 20), rel=0.3)


def test_atr_positive(candles):
    out = atr(candles, 14)
    assert all(v > 0 for v in out)


def test_rsi_bounds(candles):
    out = rsi([x["close"] for x in candles], 14)
    assert all(0 <= v <= 100 for v in out)


def test_stdev_bounds(candles):
    out = stdev([x["close"] for x in candles], 20)
    assert out[0] == 0
    assert all(v >= 0 for v in out)


def test_indicators_shape(candles, ind):
    n = len(candles)
    for key, arr in ind.items():
        assert len(arr) == n, f"{key} length {len(arr)} != {n}"


# --- signals -------------------------------------------------------------

@pytest.mark.parametrize("sid", [s[0] for s in STRATEGIES])
def test_signal_side_and_reason(sid, candles, ind):
    side, reason = signal(sid, candles, len(candles) - 1, {}, ind)
    assert side in (-1, 0, 1)
    assert isinstance(reason, str) and reason


def test_signal_unknown_strategy(candles, ind):
    side, reason = signal("not_a_strategy", candles, 300, {}, ind)
    assert side == 0
    assert reason == "Unknown strategy"


def test_signal_insufficient_bars(candles, ind):
    side, reason = signal("ema144_pullback", candles, 3, {}, ind)
    assert side == 0
    assert reason == "Insufficient bars"


def test_ichimoku_waiting(candles, ind):
    side, reason = signal("ichimoku", candles, 30, {}, ind)
    assert side == 0
    assert "history" in reason


# --- backtest ------------------------------------------------------------

def test_backtest_deterministic(candles):
    a = backtest(candles, "ema144_pullback")
    b = backtest(candles, "ema144_pullback")
    assert a["metrics"] == b["metrics"]
    assert a["equity_curve"] == b["equity_curve"]


def test_backtest_metrics_keys(candles):
    res = backtest(candles, "bb_rsi")
    for key in ("net_pnl", "ending_equity", "max_drawdown_pct", "trades",
                "win_rate", "profit_factor", "expectancy", "sharpe", "sortino"):
        assert key in res["metrics"]
    assert res["metrics"]["trades"] >= 0


def test_backtest_short_input_no_crash():
    res = backtest(make_candles(230), "ema144_pullback")
    assert res["metrics"]["trades"] >= 0


def test_backtest_all_strategies_run(candles):
    for sid, _, _ in STRATEGIES:
        res = backtest(candles, sid)
        assert res["strategy"] == sid


def test_optimize_sorted_and_bounded(candles):
    runs = optimize(candles, "bb_rsi", {"sizer": ["fixed_lot"]})  # unused key is harmless
    assert isinstance(runs, list)
    pnls = [r["metrics"]["net_pnl"] for r in runs]
    assert pnls == sorted(pnls, reverse=True)


# --- position sizing -----------------------------------------------------

def test_fixed_lot():
    assert position_size("fixed_lot", 10000, 1, 25, 5000,
                         state={"fixed_lot": 0.15}) == 0.15


def test_fixed_fractional():
    size = position_size("fixed_fractional", 10000, 1, 25, 5000)
    assert size == pytest.approx(0.04)


def test_kelly_quarter_formula():
    # kelly = (win - (1-win)/rr) / 4, capped at 0.25; size = equity*kelly/stopdist
    size = position_size("kelly_quarter", 10000, 1, 25, 5000,
                         stats={"win_rate": 0.8, "payoff": 2})
    assert size == pytest.approx(0.7)  # kelly 0.175 * 10000 / 2500
    size_high = position_size("kelly_quarter", 10000, 1, 25, 5000,
                              stats={"win_rate": 1.0, "payoff": 1})
    assert size_high == pytest.approx(1.0)  # kelly capped at 0.25


def test_grid_dca_exposure_cap():
    capped = position_size("grid_dca", 10000, 1, 25, 5000,
                           state={"exposure_remaining": 0.01})
    assert capped == pytest.approx(0.01)
    uncapped = position_size("grid_dca", 10000, 1, 25, 5000)
    assert uncapped == pytest.approx(0.04)


def test_all_sizers_return_positive(candles):
    for method in SIZERS:
        size = position_size(method, 10000, 1, 25, 5000)
        assert size > 0


# --- risk manager --------------------------------------------------------

def test_risk_allows_clean_order():
    rm = RiskManager()
    d = rm.check(0.1, 0, 0.0, 0.18)
    assert d["allowed"] is True
    assert d["reasons"] == []


def test_risk_blocks_halted():
    rm = RiskManager()
    rm.kill()
    assert rm.check(0.1, 0, 0, 0)["allowed"] is False


def test_risk_blocks_max_positions():
    rm = RiskManager(max_positions=2)
    assert rm.check(0.1, 2, 0, 0)["allowed"] is False


def test_risk_blocks_max_lot():
    rm = RiskManager(max_lot=1.0)
    assert rm.check(2.0, 0, 0, 0)["allowed"] is False


def test_risk_blocks_daily_loss():
    rm = RiskManager(daily_loss=500)
    rm.realized = -600
    assert rm.check(0.1, 0, 0, 0)["allowed"] is False


def test_risk_blocks_exposure():
    rm = RiskManager(max_exposure=3)
    assert rm.check(1.0, 1, 2.5, 0)["allowed"] is False


def test_risk_blocks_spread_guard():
    rm = RiskManager(spread_guard=1.0)
    assert rm.check(0.1, 0, 0, 2.5)["allowed"] is False


# --- monte carlo ---------------------------------------------------------

def test_monte_carlo_basic():
    res = monte_carlo([{"pnl": 100}, {"pnl": -30}], runs=200, initial=10000)
    assert res["runs"] == 200
    assert res["risk_of_ruin_pct"] >= 0
    assert res["median_ending_equity"] > 0


def test_monte_carlo_empty_trades():
    res = monte_carlo([], runs=100, initial=10000)
    assert res["risk_of_ruin_pct"] == 0
    assert res["median_ending_equity"] == 10000


def test_monte_carlo_ignores_missing_pnl():
    res = monte_carlo([{"pnl": None}, {"pnl": 40}, {}, {"pnl": -20}],
                      runs=100, initial=10000)
    assert res["runs"] == 100
    assert res["risk_of_ruin_pct"] >= 0


# --- journal -------------------------------------------------------------

def test_journal_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    j = Journal(str(db))
    rid = j.add(mode="paper", side="buy", lots=0.2, entry=5010.0,
                strategy="manual", reason="test", raw={"k": "v"})
    assert rid > 0
    rows = j.list(10)
    assert len(rows) == 1
    assert rows[0]["mode"] == "paper"
    assert rows[0]["reason"] == "test"
    assert rows[0]["raw"] == '{"k": "v"}'
    j.db.close()


def test_journal_limit(tmp_path):
    db = tmp_path / "test.db"
    j = Journal(str(db))
    for i in range(5):
        j.add(mode="paper", reason=f"r{i}")
    assert len(j.list(2)) == 2
    assert len(j.list(100)) == 5
    j.db.close()

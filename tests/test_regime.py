import engine
from regime import (
    FALLBACK_STRATEGY,
    REGIME_STRATEGIES,
    classify_regime,
    select_strategy,
)

# 60 dummy closed bars: classify_regime only uses the length when an explicit
# indicator bundle is supplied, which keeps these tests deterministic.
BARS = [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1}] * 60


def bundle(adx, atr, close=1.1, ema50=1.1, ema200=1.0):
    return {
        "cl": [1.0, close],
        "strength": [0.0, adx],
        "av": atr,
        "e50": [1.0, ema50],
        "e200": [1.0, ema200],
    }


def test_regime_map_only_references_known_strategies():
    known = {sid for sid, _, _ in engine.STRATEGIES}
    assert set(REGIME_STRATEGIES.values()) <= known
    assert FALLBACK_STRATEGY in known


def test_short_history_is_transition_with_valid_strategy():
    sid, regime = select_strategy([BARS[0]] * 10)
    assert regime["regime"] == "transition"
    assert sid == FALLBACK_STRATEGY


def test_regime_boundaries():
    flat = [1.0] * 120
    assert classify_regime(BARS, bundle(30, flat))["regime"] == "trend"
    assert classify_regime(BARS, bundle(10, flat))["regime"] == "range"
    # ATR collapses to half its median while trend strength is weak -> squeeze.
    squeeze = flat[:-1] + [0.5]
    assert classify_regime(BARS, bundle(10, squeeze))["regime"] == "squeeze"
    # ATR doubles while some trend strength is present -> volatile trend.
    spike = flat[:-1] + [2.0]
    assert classify_regime(BARS, bundle(20, spike))["regime"] == "volatile_trend"
    # ADX between the range and trend thresholds -> transition.
    assert classify_regime(BARS, bundle(21, flat))["regime"] == "transition"


def test_regime_reports_direction():
    up = classify_regime(BARS, bundle(30, [1.0] * 120, close=1.2, ema50=1.15, ema200=1.0))
    down = classify_regime(BARS, bundle(30, [1.0] * 120, close=0.9, ema50=0.95, ema200=1.0))
    assert up["direction"] == 1
    assert down["direction"] == -1


def test_selection_maps_each_regime_to_its_strategy():
    flat = [1.0] * 120
    squeeze = flat[:-1] + [0.5]
    spike = flat[:-1] + [2.0]
    cases = {
        "trend": (bundle(30, flat), "momentum_breadth_vol"),
        "range": (bundle(10, flat), "bb_rsi"),
        "squeeze": (bundle(10, squeeze), "keltner_squeeze"),
        "volatile_trend": (bundle(20, spike), "atr_expansion"),
        "transition": (bundle(21, flat), "ema144_pullback"),
    }
    for regime, (ind, expected) in cases.items():
        sid, info = select_strategy(BARS, ind)
        assert sid == expected, regime
        assert info["strategy"] == expected


def test_pool_restricts_and_ignores_unknown_entries():
    parent = bundle(30, [1.0] * 120)  # would normally pick momentum_breadth_vol
    sid, _ = select_strategy(BARS, parent, pool=["bb_rsi", "not_a_strategy"])
    assert sid == "bb_rsi"
    sid, _ = select_strategy(BARS, parent, pool=["nope"])
    assert sid == "momentum_breadth_vol"

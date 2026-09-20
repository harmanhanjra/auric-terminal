"""Deterministic market-regime classification and automatic strategy selection.

The engine can run with ``ENGINE_STRATEGY=auto`` so the strategy is chosen from
the current closed-bar context instead of being fixed at deployment time.
Selection is rule-based and reproducible: no randomness, and no look-ahead
beyond the most recent closed bar (callers pass already-closed candles).
"""
from __future__ import annotations

from statistics import median

from engine import STRATEGIES, indicators

#: Regime -> preferred strategy id.  Every value must exist in ``STRATEGIES``;
#: :func:`select_strategy` falls back to :data:`FALLBACK_STRATEGY` otherwise.
REGIME_STRATEGIES = {
    "squeeze": "keltner_squeeze",
    "range": "bb_rsi",
    "trend": "momentum_breadth_vol",
    "volatile_trend": "atr_expansion",
    "transition": "ema144_pullback",
}

FALLBACK_STRATEGY = "ema144_pullback"

#: ADX thresholds separating trend from range conditions.
TREND_ADX = 25.0
RANGE_ADX = 18.0
#: ATR-expansion thresholds as a ratio of last ATR to its recent median.
HIGH_VOL = 1.5
LOW_VOL = 0.75
#: Minimum closed bars required before a regime can be classified.
MIN_BARS = 60


def classify_regime(candles, ind=None, lookback: int = 120) -> dict:
    """Classify the closed-bar regime into ``trend``/``range``/``squeeze``/…"""
    if candles is None or len(candles) < MIN_BARS:
        return {"regime": "transition", "adx": 0.0, "volRatio": 1.0,
                "direction": 0, "reason": "Insufficient bars for regime classification"}

    ind = ind if ind is not None else indicators(candles)
    adx = float(ind["strength"][-1])
    atr_now = float(ind["av"][-1])
    history = [x for x in ind["av"][-lookback:] if x > 0]
    atr_median = median(history) if history else atr_now
    vol_ratio = atr_now / atr_median if atr_median > 0 else 1.0

    close = float(ind["cl"][-1])
    ema50, ema200 = float(ind["e50"][-1]), float(ind["e200"][-1])
    if ema50 >= ema200 and close >= ema50:
        direction = 1
    elif ema50 <= ema200 and close <= ema50:
        direction = -1
    else:
        direction = 0

    if vol_ratio <= LOW_VOL and adx < TREND_ADX:
        regime = "squeeze"
    elif vol_ratio >= HIGH_VOL and adx >= RANGE_ADX:
        regime = "volatile_trend"
    elif adx >= TREND_ADX:
        regime = "trend"
    elif adx <= RANGE_ADX:
        regime = "range"
    else:
        regime = "transition"

    return {
        "regime": regime,
        "adx": round(adx, 2),
        "volRatio": round(vol_ratio, 3),
        "direction": direction,
    }


def select_strategy(candles, ind=None, pool=None) -> tuple[str, dict]:
    """Return ``(strategy_id, regime)`` chosen for the current market context.

    ``pool`` optionally restricts selection to a subset of known strategy ids;
    an empty or fully-unknown pool is ignored.
    """
    known = {sid for sid, _, _ in STRATEGIES}
    regime = classify_regime(candles, ind)
    chosen = REGIME_STRATEGIES.get(regime["regime"], FALLBACK_STRATEGY)
    if chosen not in known:
        chosen = FALLBACK_STRATEGY
    if pool:
        allowed = [sid for sid in pool if sid in known]
        if allowed and chosen not in allowed:
            chosen = allowed[0]
    regime["strategy"] = chosen
    return chosen, regime

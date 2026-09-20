"""Deterministic pre-entry filters over closed broker candles."""
import math
from statistics import median


def assess_setup(candles, higher_candles, side, reward_risk, spread):
    if side not in (-1, 1) or len(candles) < 30 or len(higher_candles) < 50:
        return {"allowed": False, "reason": "Insufficient closed-bar context"}
    if not math.isfinite(reward_risk) or reward_risk < 1.5:
        return {"allowed": False, "reason": "Reward/risk must be at least 1.5"}
    ranges = [c['high'] - c['low'] for c in candles[-31:-1]]
    normal = median(ranges)
    last = candles[-1]
    if normal <= 0 or last['high'] - last['low'] > 3 * normal:
        return {"allowed": False, "reason": "Volatility shock; wait for conditions to normalize"}
    if spread > normal * .2:
        return {"allowed": False, "reason": "Spread consumes too much of typical bar range"}
    closes = [c['close'] for c in higher_candles]
    fast, slow = sum(closes[-20:])/20, sum(closes[-50:])/50
    trend = 1 if fast > slow else -1 if fast < slow else 0
    if trend != side:
        return {"allowed": False, "reason": "Higher-timeframe trend does not confirm entry", "trend": trend}
    return {"allowed": True, "reason": "Trend, volatility, costs and reward/risk confirmed", "trend": trend}

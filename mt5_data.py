"""Validation shared by the MT5 feed and autonomous execution."""
import math
import time


def checked_tick(tick, max_age=15.0, now=None):
    now = time.time() if now is None else now
    if tick is None:
        raise ValueError("MT5 quote unavailable")
    bid, ask = float(tick.bid), float(tick.ask)
    stamp = int(getattr(tick, "time_msc", 0) or getattr(tick, "time", 0) * 1000)
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("Invalid MT5 bid/ask")
    age = now - stamp / 1000
    if age < -5 or age > max_age:
        raise ValueError("MT5 quote stale or clock out of sync")
    return bid, ask, stamp


def checked_bars(rates, minimum=210):
    if rates is None or len(rates) < minimum:
        raise ValueError("Insufficient MT5 candle history")
    result = []
    previous = 0
    for row in rates:
        bar = {k: float(row[k]) for k in ("open", "high", "low", "close")}
        stamp = int(row["time"])
        if stamp <= previous or not all(math.isfinite(v) and v > 0 for v in bar.values()):
            raise ValueError("Invalid or unordered MT5 candles")
        if bar["high"] < max(bar["open"], bar["close"]) or bar["low"] > min(bar["open"], bar["close"]):
            raise ValueError("Invalid MT5 OHLC range")
        bar.update(time=stamp, volume=float(row["tick_volume"]))
        result.append(bar)
        previous = stamp
    return result

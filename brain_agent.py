"""
AI Brain Agent for best trade setup selection.
Uses recent candles and simple heuristics. Placeholder for Nvidia LLM integration.
"""
import math
from typing import List, Dict

def _ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    ema = sum(prices[:period]) / period
    k = 2 / (period + 1)
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def analyze_symbol(candles: List[Dict], symbol: str) -> Dict:
    if not candles:
        return {"symbol": symbol, "signal": "neutral", "confidence": 0.0, "reason": "No candles"}
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    last = closes[-1]
    atr = sum(max(h - l, 0) for h, l in zip(highs[-14:], lows[-14:])) / 14
    trend = "up" if ema20 > ema50 and last > ema20 else "down" if ema20 < ema50 and last < ema20 else "sideways"
    # Simple breakout detection
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    breakout_up = last > recent_high * 0.999
    breakout_down = last < recent_low * 1.001
    if trend == "up" and breakout_up:
        signal = "buy"
        confidence = min(0.9, 0.6 + (last - ema20) / (atr + 1e-6) * 0.1)
        reason = "Uptrend + breakout above recent high"
    elif trend == "down" and breakout_down:
        signal = "sell"
        confidence = min(0.9, 0.6 + (ema20 - last) / (atr + 1e-6) * 0.1)
        reason = "Downtrend + breakdown below recent low"
    else:
        signal = "hold"
        confidence = 0.5
        reason = f"Trend {trend} without clear breakout"
    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": round(float(confidence), 3),
        "trend": trend,
        "ema20": round(ema20, 5),
        "ema50": round(ema50, 5),
        "atr": round(atr, 5),
        "reason": reason,
        "model": "Auric Brain v1 heuristic",
        "llm": "Nvidia LLM placeholder"
    }

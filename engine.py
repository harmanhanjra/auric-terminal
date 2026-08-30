"""AuricTerminal strategy, sizing, risk, journal and backtest engine.

Pure-Python reference engine; designed for deterministic paper/demo validation.
Public API: STRATEGIES, SIZERS, sma, ema, true_ranges, atr, rsi, stdev, adx,
vwap, cross, indicators, signal, position_size, Trade, backtest, optimize,
monte_carlo, RiskManager, Journal.
"""
from __future__ import annotations

import itertools
import json
import math
import random
import sqlite3
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

STRATEGIES = [
    ("ema144_pullback", "EMA 144 + 9/21 Pullback", "trend"),
    ("triple_ema", "Triple EMA 20/50/200", "trend"),
    ("supertrend_adx", "SuperTrend + ADX", "trend"),
    ("ichimoku", "Ichimoku Kumo Breakout", "trend"),
    ("donchian", "Donchian Turtle Breakout", "trend"),
    ("bb_rsi", "Bollinger Fade + RSI", "mean_reversion"),
    ("vwap_reversion", "VWAP Deviation Reversion", "mean_reversion"),
    ("keltner_squeeze", "Keltner Squeeze Release", "mean_reversion"),
    ("rsi2", "RSI(2) Extremes", "mean_reversion"),
    ("fib_retracement", "Fibonacci Retracement", "structure"),
    ("fib_extension", "Fibonacci Extension", "structure"),
    ("bos_choch", "BOS + CHoCH", "structure"),
    ("orderblock_fvg", "Order Block + FVG", "structure"),
    ("liquidity_sweep", "Liquidity Sweep", "structure"),
    ("sr_bounce", "Support/Resistance Bounce", "structure"),
    ("asia_breakout", "Asian Range Breakout", "session"),
    ("ny_orb", "New York Opening Range", "session"),
    ("atr_expansion", "ATR Expansion Breakout", "breakout"),
    ("momentum_breadth_vol", "Momentum + Breadth + Volatility", "trend"),
]
SIZERS = ["fixed_lot", "fixed_fractional", "atr_risk", "martingale",
          "anti_martingale", "kelly_quarter", "grid_dca"]

#: XAU/USD contract size in ounces per lot (used for P/L conversion).
OUNCES_PER_LOT = 100


def sma(v, n):
    """Simple moving average with running sum (O(n))."""
    out = []
    running = 0.0
    for i, x in enumerate(v):
        running += x
        if i >= n:
            running -= v[i - n]
        out.append(running / min(n, i + 1))
    return out


def ema(v, n):
    """Exponential moving average, seeded with the first value."""
    if not v:
        return []
    k = 2 / (n + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def true_ranges(c):
    """True range for every candle."""
    out = []
    for i, x in enumerate(c):
        prev = c[i - 1]["close"] if i else x["close"]
        out.append(max(x["high"] - x["low"],
                       abs(x["high"] - prev),
                       abs(x["low"] - prev)))
    return out


def atr(c, n=14):
    """Wilder-style ATR approximated with an EMA of true ranges."""
    return ema(true_ranges(c), n)


def rsi(v, n=14):
    """Relative Strength Index (EMA-smoothed) in the range [0, 100]."""
    gains, losses = [0.0], [0.0]
    for a, b in zip(v, v[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = ema(gains, n), ema(losses, n)
    return [100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
            for g, l in zip(ag, al)]


def stdev(v, n):
    """Rolling population standard deviation with running sums (O(n))."""
    out = []
    running = 0.0
    running_sq = 0.0
    for i, x in enumerate(v):
        running += x
        running_sq += x * x
        if i >= n:
            running -= v[i - n]
            running_sq -= v[i - n] ** 2
        count = min(n, i + 1)
        if count < 2:
            out.append(0.0)
            continue
        mean = running / count
        var = max(running_sq / count - mean * mean, 0.0)
        out.append(math.sqrt(var))
    return out


def adx(c, n=14):
    """Wilder-style trend-strength proxy using directional movement / ATR."""
    plus, minus = [0.0], [0.0]
    for a, b in zip(c, c[1:]):
        up, dn = b["high"] - a["high"], a["low"] - b["low"]
        plus.append(up if up > dn and up > 0 else 0.0)
        minus.append(dn if dn > up and dn > 0 else 0.0)
    a = atr(c, n)
    p, m = ema(plus, n), ema(minus, n)
    dx = []
    for pi, mi, ai in zip(p, m, a):
        pdi, mdi = 100 * pi / max(ai, 1e-9), 100 * mi / max(ai, 1e-9)
        dx.append(100 * abs(pdi - mdi) / max(pdi + mdi, 1e-9))
    return ema(dx, n)


def vwap(c):
    """Cumulative (session) VWAP over the supplied candle series."""
    total = 0.0
    vol = 0.0
    out = []
    for x in c:
        q = float(x.get("volume", 1) or 1)
        total += ((x["high"] + x["low"] + x["close"]) / 3) * q
        vol += q
        out.append(total / vol)
    return out


def cross(a, b, i):
    """1 for an upward cross of a over b at i, -1 for downward, else 0."""
    if i < 1:
        return 0
    if a[i] > b[i] and a[i - 1] <= b[i - 1]:
        return 1
    if a[i] < b[i] and a[i - 1] >= b[i - 1]:
        return -1
    return 0


def indicators(c):
    """Precompute all indicator arrays once per backtest instead of per bar."""
    cl = [x["close"] for x in c]
    hi = [x["high"] for x in c]
    lo = [x["low"] for x in c]
    vw = vwap(c)
    return {
        "cl": cl, "hi": hi, "lo": lo,
        "e9": ema(cl, 9), "e21": ema(cl, 21), "e20": ema(cl, 20),
        "e50": ema(cl, 50), "e144": ema(cl, 144), "e200": ema(cl, 200),
        "rv": rsi(cl, 14), "rv2": rsi(cl, 2), "av": atr(c, 14),
        "strength": adx(c, 14), "sma20": sma(cl, 20), "sd20": stdev(cl, 20),
        "vwap": vw, "vwdev": stdev([x - v for x, v in zip(cl, vw)], 20),
    }


def _breakout_signal(hi, lo, close, i, n, label):
    """Generic channel/session breakout signal."""
    if close[i] > max(hi[max(0, i - n):i]):
        return 1, label
    if close[i] < min(lo[max(0, i - n):i]):
        return -1, label
    return 0, label


def signal(strategy_id, c, i, params=None, ind=None):
    """Evaluate one strategy on bar *i*.

    Returns ``(side, reason)`` where side is -1, 0 or 1.
    """
    p = params or {}
    if ind is None:
        ind = indicators(c)
    if i < 5:
        return 0, "Insufficient bars"

    cl, hi, lo = ind["cl"], ind["hi"], ind["lo"]
    av, strength = ind["av"], ind["strength"]
    e9, e21, e20, e50, e144, e200 = (ind["e9"], ind["e21"], ind["e20"],
                                     ind["e50"], ind["e144"], ind["e200"])
    rv, rv2 = ind["rv"], ind["rv2"]

    if strategy_id == "ema144_pullback":
        s = cross(e9, e21, i)
        ok = (s > 0 and cl[i] > e144[i]) or (s < 0 and cl[i] < e144[i])
        return (s if ok else 0), (f"9/21 cross {'above' if cl[i] > e144[i] else 'below'} EMA144")

    if strategy_id == "triple_ema":
        if e20[i] > e50[i] > e200[i]:
            s = 1
        elif e20[i] < e50[i] < e200[i]:
            s = -1
        else:
            s = 0
        return s, "20/50/200 ribbon alignment"

    if strategy_id == "supertrend_adx":
        mid = (hi[i] + lo[i]) / 2
        if cl[i] > mid + 2 * av[i]:
            s = 1
        elif cl[i] < mid - 2 * av[i]:
            s = -1
        else:
            s = 0
        return (s if strength[i] > p.get("adx", 25) else 0), f"ATR trend band with ADX {strength[i]:.1f}"

    if strategy_id == "ichimoku":
        if i < 52:
            return 0, "Waiting for Ichimoku history"
        ten = (max(hi[i - 8:i + 1]) + min(lo[i - 8:i + 1])) / 2
        kij = (max(hi[i - 25:i + 1]) + min(lo[i - 25:i + 1])) / 2
        sa = (ten + kij) / 2
        sb = (max(hi[i - 51:i + 1]) + min(lo[i - 51:i + 1])) / 2
        if cl[i] > max(sa, sb):
            s = 1
        elif cl[i] < min(sa, sb):
            s = -1
        else:
            s = 0
        return s, "Price outside Kumo cloud"

    if strategy_id == "donchian":
        n = int(p.get("period", 20))
        return _breakout_signal(hi, lo, cl, i, n, "Donchian channel break")

    if strategy_id == "bb_rsi":
        m, sd = ind["sma20"], ind["sd20"]
        if cl[i] < m[i] - 2 * sd[i] and rv[i] < 35:
            s = 1
        elif cl[i] > m[i] + 2 * sd[i] and rv[i] > 65:
            s = -1
        else:
            s = 0
        return s, f"Bollinger extreme with RSI {rv[i]:.1f}"

    if strategy_id == "vwap_reversion":
        vw, dev = ind["vwap"], ind["vwdev"]
        if cl[i] < vw[i] - 2 * dev[i]:
            s = 1
        elif cl[i] > vw[i] + 2 * dev[i]:
            s = -1
        else:
            s = 0
        return s, "Price beyond 2σ VWAP band"

    if strategy_id == "keltner_squeeze":
        m, sd = ind["sma20"], ind["sd20"]
        squeeze = 2 * sd[i] < 1.5 * av[i]
        if squeeze and cl[i] > hi[i - 1]:
            s = 1
        elif squeeze and cl[i] < lo[i - 1]:
            s = -1
        else:
            s = 0
        return s, "Bollinger width inside Keltner then range break"

    if strategy_id == "rsi2":
        if rv2[i] < 5:
            return 1, f"RSI(2)={rv2[i]:.1f}"
        if rv2[i] > 95:
            return -1, f"RSI(2)={rv2[i]:.1f}"
        return 0, f"RSI(2)={rv2[i]:.1f}"

    if strategy_id == "fib_retracement":
        n = 30
        wh, wl = hi[max(0, i - n):i], lo[max(0, i - n):i]
        H, L = max(wh), min(wl)
        long_lv = L + .618 * (H - L)
        short_lv = H - .618 * (H - L)
        if abs(cl[i] - long_lv) < .15 * av[i] and cl[i] > e50[i]:
            s = 1
        elif abs(cl[i] - short_lv) < .15 * av[i] and cl[i] < e50[i]:
            s = -1
        else:
            s = 0
        return s, "Price testing auto-detected Fibonacci retracement"

    if strategy_id == "fib_extension":
        n = 30
        wh, wl = hi[max(0, i - n):i], lo[max(0, i - n):i]
        H, L = max(wh), min(wl)
        rising = wh.index(H) >= wl.index(L)
        if (rising and abs(cl[i] - (H + .618 * (H - L))) < .25 * av[i]
                and cl[i] > e50[i]):
            s = 1
        elif (not rising and abs(cl[i] - (L - .618 * (H - L))) < .25 * av[i]
              and cl[i] < e50[i]):
            s = -1
        else:
            s = 0
        return s, "Price extending toward 1.618 Fibonacci projection"

    if strategy_id == "bos_choch":
        return _breakout_signal(hi, lo, cl, i, 5, "Five-bar structure break")

    if strategy_id == "orderblock_fvg":
        bull = lo[i] > hi[i - 2] and c[i - 1]["close"] > c[i - 1]["open"]
        bear = hi[i] < lo[i - 2] and c[i - 1]["close"] < c[i - 1]["open"]
        return (1 if bull else -1 if bear else 0), "Three-candle fair-value gap"

    if strategy_id == "liquidity_sweep":
        if lo[i] < min(lo[i - 5:i]) and cl[i] > lo[i - 1]:
            s = 1
        elif hi[i] > max(hi[i - 5:i]) and cl[i] < hi[i - 1]:
            s = -1
        else:
            s = 0
        return s, "Prior liquidity taken and candle reclaimed"

    if strategy_id == "sr_bounce":
        support = min(lo[max(0, i - 30):i])
        res = max(hi[max(0, i - 30):i])
        if abs(lo[i] - support) < .2 * av[i] and cl[i] > c[i]["open"]:
            s = 1
        elif abs(hi[i] - res) < .2 * av[i] and cl[i] < c[i]["open"]:
            s = -1
        else:
            s = 0
        return s, "Reaction at clustered 30-bar level"

    if strategy_id in ("asia_breakout", "ny_orb"):
        n = 24 if strategy_id == "asia_breakout" else 4
        return _breakout_signal(hi, lo, cl, i, n, f"{n}-bar session range break")

    if strategy_id == "atr_expansion":
        body = abs(cl[i] - c[i]["open"])
        if body > 1.5 * av[i] and cl[i] > c[i]["open"]:
            s = 1
        elif body > 1.5 * av[i]:
            s = -1
        else:
            s = 0
        return s, "Candle body exceeds 1.5 ATR"

    if strategy_id == "momentum_breadth_vol":
        mom = int(p.get("mom", 30))
        bn = int(p.get("breadth_n", 20))
        vn = int(p.get("vol_n", 20))
        if i < max(mom, bn, vn):
            return 0, "Building multi-factor history"
        roc = (cl[i] - cl[i - mom]) / max(cl[i - mom], 1e-9)
        br = sum(1 for j in range(i - bn + 1, i + 1) if cl[j] > cl[j - 1]) / bn
        vr = av[i] / max(statistics.mean(av[i - vn + 1:i + 1]), 1e-9)
        rmin = p.get("roc_min", .001)
        thr = p.get("breadth_thr", .55)
        vmax = p.get("vol_max", 1.6)
        if vr > vmax:
            return 0, f"Volatility regime {vr:.2f}x ATR — standing aside"
        if roc > rmin and br >= thr:
            return 1, f"Multi-factor LONG · ROC {roc * 100:.1f}% · breadth {br * 100:.0f}% · vol {vr:.2f}"
        if roc < -rmin and br <= 1 - thr:
            return -1, f"Multi-factor SHORT · ROC {roc * 100:.1f}% · breadth {br * 100:.0f}% · vol {vr:.2f}"
        return 0, f"Factors disagree · ROC {roc * 100:.1f}% · breadth {br * 100:.0f}%"

    return 0, "Unknown strategy"


def position_size(method, equity, risk_pct, stop_distance, price,
                  stats=None, state=None):
    """Return a lot size for the requested sizing model.

    * ``stats`` holds observed trade statistics (for Kelly sizing).
    * ``state`` holds live context such as loss/win streaks, the fixed lot
      and remaining exposure (for grid/DCA sizing).
    """
    stats = stats or {}
    state = state or {}
    base = max(.01, (equity * risk_pct / 100) / max(stop_distance * OUNCES_PER_LOT, 1e-9))

    if method == "fixed_lot":
        return float(state.get("fixed_lot", .1))
    if method in ("fixed_fractional", "atr_risk"):
        return base
    if method == "martingale":
        multiplier = float(state.get("multiplier", 2)) ** min(int(state.get("loss_streak", 0)), int(state.get("max_steps", 3)))
        return base * min(multiplier, 8)
    if method == "anti_martingale":
        return base * (1 + min(int(state.get("win_streak", 0)), 3) * .5)
    if method == "kelly_quarter":
        win = stats.get("win_rate", .5)
        rr = stats.get("payoff", 1)
        kelly = max(0.0, min(.25, (win - (1 - win) / max(rr, .01)) / 4))
        return max(.01, equity * kelly / max(stop_distance * OUNCES_PER_LOT, 1e-9))
    if method == "grid_dca":
        remaining = state.get("exposure_remaining")
        return min(base, float(remaining)) if remaining is not None else base
    return base


@dataclass
class Trade:
    side: int
    entry: float
    exit: float
    size: float
    pnl: float
    entry_i: int
    exit_i: int
    reason: str


def backtest(candles, strategy_id="ema144_pullback", params=None, initial=10000,
             risk_pct=1, sizer="fixed_fractional", spread=.18, slippage=.05,
             commission=0, atr_stop=1.5, rr=2, max_exposure=3):
    """Event-driven backtest over ``candles``.

    One position at a time; exits on ATR stop or R-multiple target on the bar
    after entry. Prices are bumped by half-spread + slippage in the entry
    direction. Metrics match the UI: net P/L, max drawdown, win rate, profit
    factor, expectancy, Sharpe and Sortino.
    """
    equity = initial
    peak = initial
    curve = [initial]
    trades = []
    pos = None
    loss_streak = win_streak = 0
    ind = indicators(candles)
    av = ind["av"]

    for i in range(210, len(candles)):
        x = candles[i]

        if pos:
            stop, target = pos["stop"], pos["target"]
            exit_price = None
            why = ""
            if pos["side"] > 0 and x["low"] <= stop:
                exit_price, why = stop, "Stop"
            elif pos["side"] > 0 and x["high"] >= target:
                exit_price, why = target, "Target"
            elif pos["side"] < 0 and x["high"] >= stop:
                exit_price, why = stop, "Stop"
            elif pos["side"] < 0 and x["low"] <= target:
                exit_price, why = target, "Target"
            if exit_price is not None:
                pnl = ((exit_price - pos["entry"]) * pos["side"] * pos["size"]
                       * OUNCES_PER_LOT - commission)
                equity += pnl
                trades.append(Trade(pos["side"], pos["entry"], exit_price,
                                    pos["size"], pnl, pos["i"], i, why))
                loss_streak = loss_streak + 1 if pnl < 0 else 0
                win_streak = win_streak + 1 if pnl > 0 else 0
                pos = None

        if not pos:
            s, reason = signal(strategy_id, candles, i, params, ind)
            if s:
                dist = max(av[i] * atr_stop, .1)
                state = {
                    "loss_streak": loss_streak,
                    "win_streak": win_streak,
                    # single position at a time, so full ceiling is free on entry
                    "exposure_remaining": float(max_exposure),
                }
                size = position_size(sizer, equity, risk_pct, dist,
                                     x["close"], state=state)
                entry = x["close"] + (spread / 2 + slippage) * s
                pos = {"side": s, "entry": entry, "stop": entry - dist * s,
                       "target": entry + dist * rr * s, "size": round(size, 2),
                       "i": i, "reason": reason}

        curve.append(equity)
        peak = max(peak, equity)

    pnls = [t.pnl for t in trades]
    wins = [v for v in pnls if v > 0]
    losses = [v for v in pnls if v < 0]
    returns = [(curve[i] - curve[i - 1]) / max(curve[i - 1], 1)
               for i in range(1, len(curve))]

    maxdd = 0.0
    pk = curve[0]
    for e in curve:
        pk = max(pk, e)
        maxdd = max(maxdd, (pk - e) / pk * 100)

    mean = statistics.mean(returns) if returns else 0.0
    sd = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    downs = [r for r in returns if r < 0]
    down = statistics.pstdev(downs) if len(downs) > 1 else 0.0

    metrics = {
        "net_pnl": round(equity - initial, 2),
        "ending_equity": round(equity, 2),
        "max_drawdown_pct": round(maxdd, 2),
        "trades": len(trades),
        "win_rate": round(100 * len(wins) / max(len(pnls), 1), 2),
        "profit_factor": round(sum(wins) / max(abs(sum(losses)), 1e-9), 2),
        "expectancy": round(statistics.mean(pnls), 2) if pnls else 0,
        "sharpe": round(mean / sd * math.sqrt(252), 2) if sd else 0,
        "sortino": round(mean / down * math.sqrt(252), 2) if down else 0,
    }
    return {"strategy": strategy_id, "metrics": metrics,
            "equity_curve": [round(x, 2) for x in curve],
            "trades": [asdict(t) for t in trades]}


def optimize(candles, strategy_id, grid):
    """Grid search over the parameter grid, sorted best P/L first."""
    keys = list(grid)
    runs = []
    for values in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, values))
        r = backtest(candles, strategy_id, p)
        runs.append({"params": p, "metrics": r["metrics"]})
    runs.sort(key=lambda x: (x["metrics"]["net_pnl"],
                             -x["metrics"]["max_drawdown_pct"]), reverse=True)
    return runs


def monte_carlo(trades, runs=1000, initial=10000):
    """Resample observed trade P/Ls with replacement and report ruin risk."""
    pnls = []
    for t in trades:
        try:
            value = float(t.get("pnl", 0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            pnls.append(value)
    if not pnls:
        return {"runs": runs, "risk_of_ruin_pct": 0,
                "median_ending_equity": initial, "p05": initial, "p95": initial}

    endings = []
    ruin = 0
    for _ in range(min(runs, 5000)):
        eq = initial
        peak = initial
        bad = False
        for _ in pnls:
            eq += random.choice(pnls)
            peak = max(peak, eq)
            bad |= eq <= initial * .5
        endings.append(eq)
        ruin += int(bad)
    endings.sort()

    def q(p):
        return endings[min(len(endings) - 1, int(p * (len(endings) - 1)))]

    return {"runs": runs, "risk_of_ruin_pct": round(100 * ruin / runs, 2),
            "median_ending_equity": round(q(.5), 2), "p05": round(q(.05), 2),
            "p95": round(q(.95), 2)}


class RiskManager:
    """Server-side risk guards re-checked on every entry, independent of UI."""

    def __init__(self, daily_loss=500, max_positions=3, max_lot=1,
                 max_exposure=3, spread_guard=1):
        self.daily_loss = daily_loss
        self.max_positions = max_positions
        self.max_lot = max_lot
        self.max_exposure = max_exposure
        self.spread_guard = spread_guard
        self.realized = 0
        self.halted = False

    def check(self, lots, positions, exposure, spread):
        reasons = []
        if self.halted:
            reasons.append("Trading halted")
        if self.realized <= -self.daily_loss:
            reasons.append("Daily loss limit reached")
        if positions >= self.max_positions:
            reasons.append("Max concurrent positions reached")
        if lots > self.max_lot:
            reasons.append("Max lot exceeded")
        if exposure + lots > self.max_exposure:
            reasons.append("Exposure ceiling exceeded")
        if spread > self.spread_guard:
            reasons.append("Spread guard active")
        return {"allowed": not reasons, "reasons": reasons}

    def kill(self):
        self.halted = True


class Journal:
    """SQLite trade journal. Safe to use from a single async loop thread."""

    def __init__(self, path="auric.db"):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS journal("
            "id INTEGER PRIMARY KEY, ts INTEGER, mode TEXT, symbol TEXT, "
            "side TEXT, lots REAL, entry REAL, exit REAL, pnl REAL, "
            "strategy TEXT, reason TEXT, notes TEXT, raw TEXT)")
        self.db.commit()

    def add(self, **row):
        data = {
            "ts": int(time.time() * 1000), "mode": "paper", "symbol": "XAUUSD",
            "side": "", "lots": 0, "entry": 0, "exit": None, "pnl": None,
            "strategy": "manual", "reason": "", "notes": "", **row,
        }
        cols = list(data)
        vals = [json.dumps(data[x]) if x == "raw" and not isinstance(data[x], str)
                else data[x] for x in cols]
        placeholders = ",".join("?" * len(cols))
        query = f"INSERT INTO journal({','.join(cols)}) VALUES({placeholders})"
        cur = self.db.execute(query, vals)
        self.db.commit()
        return cur.lastrowid

    def list(self, limit=200):
        rows = self.db.execute(
            "SELECT * FROM journal ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(x) for x in rows.fetchall()]

"""Multi-symbol engine — runs independent engine loops + Kronos forecasts per symbol.

Each symbol gets its own config, state, Kronos cache, and risk check.
The server.py endpoints read from ENGINES dict to serve per-symbol status.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List

logger = logging.getLogger("auric.multi")

# ── Local confirmations fallback (server defines confirmations) ────────────
def _local_confirmations(candles, ind=None):
    try:
        from engine import signal, STRATEGIES
        bull = bear = 0
        for sid, _, _ in STRATEGIES:
            s, _ = signal(sid, candles, len(candles) - 1, {}, ind)
            bull += int(s > 0)
            bear += int(s < 0)
        return {"bull": bull, "bear": bear}
    except Exception:
        return {"bull": 0, "bear": 0}

# ── Symbol registry ──────────────────────────────────────────────────────────
SYMBOLS: List[str] = [
    "XAUUSD", "BTCUSD", "EURUSD",
]

PROTECTED_SYMBOLS: set[str] = {"XAUUSD", "BTCUSD", "EURUSD"}

SYMBOL_PROPS: Dict[str, Dict[str, Any]] = {
    "XAUUSD":  {"digits": 2, "point": 0.01,  "category": "metals"},
    "BTCUSD":  {"digits": 2, "point": 0.01,  "category": "crypto"},
    "EURUSD":  {"digits": 5, "point": 1e-5,  "category": "forex"},
}


class SymbolEngine:
    """Self-contained engine instance for one trading symbol."""

    def __init__(self, symbol: str, mt5_mod, mt5_ready_ref: dict,
                 magic: int, live_enabled: bool, max_lot: float,
                 max_daily_loss: float, journal, tg_notify_fn,
                 kronos_engine_mod, kronos_ok: bool, mt5_timeframes: dict,
                 engine_mod):
        self.symbol = symbol
        self.mt5 = mt5_mod
        self._mt5_ready = mt5_ready_ref  # shared mutable ref
        self.magic = magic
        self.live_enabled = live_enabled
        self.max_lot = max_lot
        self.max_daily_loss = max_daily_loss
        self.journal = journal
        self.tg_notify = tg_notify_fn
        self.kronos_engine = kronos_engine_mod
        self.kronos_ok = kronos_ok
        self.mt5_timeframes = mt5_timeframes
        self.engine_mod = engine_mod

        # Per-symbol engine config (all symbols share same defaults)
        self.config: Dict[str, Any] = {
            "enabled": os.getenv("ENGINE_ENABLED", "true").lower() == "true",
            "strategy": os.getenv("ENGINE_STRATEGY", "ema144_pullback"),
            "timeframe": os.getenv("ENGINE_TIMEFRAME", "M15"),
            "risk_pct": float(os.getenv("ENGINE_RISK_PCT", "1")),
            "sizer": os.getenv("ENGINE_SIZER", "fixed_fractional"),
            "atr_stop": float(os.getenv("ENGINE_ATR_STOP", "1.5")),
            "rr": float(os.getenv("ENGINE_RR", "2")),
            "trail_atr": float(os.getenv("ENGINE_TRAIL_ATR", "1.0")),
            "confirm_min": int(os.getenv("ENGINE_CONFIRM_MIN", "3")),
            "pyramid_frac": float(os.getenv("ENGINE_PYRAMID_FRAC", "0.5")),
            "max_pyramid": int(os.getenv("ENGINE_MAX_PYRAMID", "2")),
        }

        self.state: Dict[str, Any] = {
            "running": False, "last_bar": None, "signal": None,
            "error": None, "trades": 0, "status": "stopped",
            "log": [], "pyramid_count": 0,
        }

        self.kronos_cache: Dict[str, Any] = {
            "direction": 0, "confidence": 0.0, "pct_change": 0.0,
            "forecast_close": 0.0, "last_close": 0.0,
            "timestamp": 0, "error": None,
            "model": os.getenv("KRONOS_MODEL", "mini"),
        }

        # Per-symbol risk manager
        from engine import RiskManager
        self.risk = RiskManager(daily_loss=max_daily_loss, max_lot=max_lot)

        # Kronos config (shared)
        self.kronos_confirm = os.getenv("ENGINE_KRONOS_CONFIRM", "true").lower() == "true"
        self.kronos_poll = int(os.getenv("KRONOS_POLL_SECONDS", "120"))
        self.kronos_lookback = int(os.getenv("KRONOS_LOOKBACK", "400"))
        self.kronos_pred_len = int(os.getenv("KRONOS_PRED_LEN", "60"))
        self.kronos_model_id = os.getenv("KRONOS_MODEL", "mini")
        self.kronos_veto_threshold = float(os.getenv("KRONOS_VETO_THRESHOLD", "0.3"))

        self._task_engine: asyncio.Task | None = None
        self._task_kronos: asyncio.Task | None = None
        # In-memory paper position (Journal has no open-position tracking).
        self._paper_position: dict | None = None

    # ── Snapshot for API ──────────────────────────────────────────────────
    def snapshot(self) -> dict:
        running = (self.config["enabled"]
                   and self.state["status"] not in ("stopped", "disabled",
                                                     "mt5_offline", "halted",
                                                     "no_data"))
        props = SYMBOL_PROPS.get(self.symbol, {})
        return {
            "symbol": self.symbol,
            "category": props.get("category", "unknown"),
            "running": running,
            "enabled": self.config["enabled"],
            "strategy": self.config["strategy"],
            "timeframe": self.config["timeframe"],
            "status": self.state["status"],
            "lastBar": self.state["last_bar"],
            "signal": self.state["signal"],
            "error": self.state["error"],
            "trades": self.state["trades"],
            "log": list(self.state["log"]),
            "pyramids": self.state["pyramid_count"],
            "kronos": {
                "enabled": self.kronos_confirm,
                "available": self.kronos_ok,
                "direction": self.kronos_cache["direction"],
                "confidence": self.kronos_cache["confidence"],
                "pctChange": self.kronos_cache["pct_change"],
                "forecastClose": self.kronos_cache["forecast_close"],
                "lastClose": self.kronos_cache["last_close"],
                "model": self.kronos_cache["model"],
                "ageSeconds": (round((time.time() * 1000 - self.kronos_cache["timestamp"]) / 1000, 1)
                               if self.kronos_cache["timestamp"] else None),
                "error": self.kronos_cache["error"],
            },
        }

    # ── Engine log helper ─────────────────────────────────────────────────
    def _log(self, entry: dict):
        entry["ts"] = int(time.time() * 1000)
        self.state["log"].insert(0, entry)
        del self.state["log"][60:]

    # ── Kronos agreement check ────────────────────────────────────────────
    def _kronos_agrees(self, side: int) -> dict:
        if not self.kronos_confirm:
            return {"ok": True, "reason": "Kronos disabled",
                    "kronos_dir": 0, "confidence": 0.0}

        age_s = (time.time() * 1000 - self.kronos_cache["timestamp"]) / 1000.0
        if age_s > self.kronos_poll * 5 or self.kronos_cache["error"]:
            return {"ok": True, "reason": "Kronos stale — passing through",
                    "kronos_dir": 0, "confidence": 0.0}

        k_dir = self.kronos_cache["direction"]
        conf = self.kronos_cache["confidence"]

        if k_dir == 0 or conf < self.kronos_veto_threshold:
            return {"ok": True,
                    "reason": f"Kronos neutral/low-conf (dir={k_dir} conf={conf:.2f})",
                    "kronos_dir": k_dir, "confidence": conf}

        if k_dir != side:
            return {"ok": False,
                    "reason": (f"Kronos VETO on {self.symbol}: signal {'LONG' if side==1 else 'SHORT'} "
                               f"but Kronos predicts {'DOWN' if k_dir==-1 else 'UP'} "
                               f"(conf {conf:.2f}, {self.kronos_cache['pct_change']:+.2f}%)"),
                    "kronos_dir": k_dir, "confidence": conf}

        return {"ok": True,
                "reason": (f"Kronos CONFIRMED {self.symbol}: dir={k_dir} conf={conf:.2f} "
                           f"{self.kronos_cache['pct_change']:+.2f}%"),
                "kronos_dir": k_dir, "confidence": conf}

    # ── Trailing stop ─────────────────────────────────────────────────────
    async def _trail(self):
        if not self.config["enabled"] or not self._mt5_ready["ok"] or not self.mt5:
            return
        if not self.live_enabled:
            self.state["status"] = "paper_only"
            return
        if self.config["trail_atr"] <= 0:
            return
        from engine import atr as _atr
        ours = [p for p in (list(await asyncio.to_thread(self.mt5.positions_get, symbol=self.symbol) or []))
                if p.magic == self.magic]
        if not ours:
            return
        tf = self.mt5_timeframes.get(self.config["timeframe"])
        if tf is None:
            return
        rates = await asyncio.to_thread(self.mt5.copy_rates_from_pos, self.symbol, tf, 0, 40)
        if rates is None or not len(rates):
            return
        candles = [{"open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"])} for r in rates]
        av = _atr(candles, 14)
        trail = max(av[-1] * self.config["trail_atr"], 0.1)
        tick = await asyncio.to_thread(self.mt5.symbol_info_tick, self.symbol)
        if not tick:
            return
        for p in ours:
            is_long = p.type == self.mt5.POSITION_TYPE_BUY
            price = tick.bid if is_long else tick.ask
            current_sl = float(p.sl) if p.sl else 0.0
            moved = None
            if is_long:
                new_sl = price - trail
                if new_sl > current_sl + 0.3 * av[-1]:
                    moved = new_sl
            else:
                new_sl = price + trail
                if new_sl < current_sl - 0.3 * av[-1]:
                    moved = new_sl
            if moved is not None:
                request = {"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol,
                           "position": p.ticket, "sl": round(moved, 2),
                           "tp": float(p.tp or 0.0), "type_time": self.mt5.ORDER_TIME_GTC}
                result = await asyncio.to_thread(self.mt5.order_send, request)
                if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:
                    self._log({"type": "trail", "side": 1 if is_long else -1,
                               "sl": round(moved, 2), "ticket": p.ticket})

    # ── Pyramiding ────────────────────────────────────────────────────────
    async def _try_pyramid(self, candles, ind, ours, open_rows, bar):
        if self.config["confirm_min"] <= 0 or self.config["max_pyramid"] <= 0:
            return
        pos = ours[0]
        is_long = pos.type == self.mt5.POSITION_TYPE_BUY
        base = float(pos.volume)
        count = int(self.state.get("pyramid_count", 0))
        if count >= self.config["max_pyramid"]:
            return
        # confirmations fallback
        conf = _local_confirmations(candles, ind)
        net = conf["bull"] - conf["bear"]
        strong = (is_long and net >= self.config["confirm_min"]) or \
                 (not is_long and -net >= self.config["confirm_min"])
        if not strong:
            return

        pyramid_side = 1 if is_long else -1
        kronos_check = self._kronos_agrees(pyramid_side)
        if not kronos_check["ok"]:
            self._log({"type": "kronos_veto", "side": pyramid_side,
                       "reason": f"Pyramid blocked: {kronos_check['reason']}",
                       "bar": bar})
            return

        total_volume = sum(float(o.volume) for o in open_rows)
        add = round(max(total_volume * self.config["pyramid_frac"], 0.01), 2)
        if add > self.max_lot:
            return
        tick = await asyncio.to_thread(self.mt5.symbol_info_tick, self.symbol)
        if not tick:
            return
        price = tick.ask if is_long else tick.bid
        order_type = self.mt5.ORDER_TYPE_BUY if is_long else self.mt5.ORDER_TYPE_SELL
        request = {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": add,
                   "type": order_type, "price": price,
                   "sl": float(pos.sl) if pos.sl else 0.0,
                   "tp": float(pos.tp) if pos.tp else 0.0,
                   "deviation": 20, "magic": self.magic, "comment": "AuricEngine+",
                   "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self.mt5.ORDER_FILLING_IOC}
        result = await asyncio.to_thread(self.mt5.order_send, request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            self.state["error"] = f"MT5 rejected pyramid: {getattr(result, 'comment', 'no response')}"
            self._log({"type": "rejected", "reason": self.state["error"], "bar": bar})
            return
        self.state["pyramid_count"] = count + 1
        self.state["trades"] += 1
        self.state["error"] = None
        self.journal.add(mode="live", side="buy" if is_long else "sell", lots=add,
                         entry=result.price, strategy=self.config["strategy"],
                         reason=f"Engine pyramid (conf {net:+d})", raw=dict(request))
        self._log({"type": "pyramid", "side": 1 if is_long else -1, "lots": add,
                    "price": result.price, "bar": bar, "ticket": result.order, "confirm": net})
        dir_str = "LONG" if is_long else "SHORT"
        await self.tg_notify(
            f"<b>Auric PYRAMID</b> {dir_str} {self.symbol}\n"
            f"+{add} lots @ {result.price} (total vol: {total_volume + add})\n"
            f"Pyramid #{count + 1} | Ticket: {result.order}")

    # ── Yahoo Finance paper trading fallback ─────────────────────────────
    YAHOO_TICKERS = {
        "XAUUSD": "GC=F", "BTCUSD": "BTC-USD",
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X", "EURJPY": "EURJPY=X",
        "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
        "USDCHF": "USDCHF=X", "NZDUSD": "NZDUSD=X",
    }
    YAHOO_INTERVALS = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
                       "H1": "1h", "H4": "1h", "D1": "1d"}

    async def _fetch_yahoo_candles(self) -> list:
        try:
            import yfinance as yf
        except ImportError:
            return []
        ticker = self.YAHOO_TICKERS.get(self.symbol, self.symbol)
        interval = self.YAHOO_INTERVALS.get(self.config["timeframe"], "15m")
        try:
            df = await asyncio.to_thread(
                lambda: yf.Ticker(ticker).history(period="60d", interval=interval))
            if df.empty:
                return []
            values = []
            for idx, row in df.iterrows():
                values.append({
                    "time": int(idx.timestamp()),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row.get("Volume", 0) or 0),
                })
            return values[-320:]
        except Exception:
            return []

    async def _get_yahoo_price(self) -> float:
        try:
            import yfinance as yf
        except ImportError:
            return 0.0
        ticker = self.YAHOO_TICKERS.get(self.symbol, self.symbol)
        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info)
            price = float(info.get("regularMarketPrice", 0) or
                          info.get("previousClose", 0) or 0)
            if price <= 0:
                hist = await asyncio.to_thread(lambda: yf.Ticker(ticker).history(period="1d"))
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            return price
        except Exception:
            return 0.0

    async def _step_yahoo(self):
        if not self.config["enabled"]:
            self.state["status"] = "disabled"
            return
        if self.risk.halted and self.symbol not in PROTECTED_SYMBOLS:
            self.state["status"] = "halted"
            return

        candles = await self._fetch_yahoo_candles()
        if not candles:
            self.state["status"] = "no_data"
            return

        bar = candles[-1]["time"]
        if self.state["last_bar"] == bar:
            return
        self.state["last_bar"] = bar

        from engine import indicators, signal as _signal, position_size

        ind = indicators(candles)

        # Manage the in-memory paper position: exit on SL/TP, else hold.
        if self._paper_position is not None:
            pp = self._paper_position
            x = candles[-1]
            exit_price = None
            why = ""
            if pp["side"] > 0 and x["low"] <= pp["stop"]:
                exit_price, why = pp["stop"], "Stop"
            elif pp["side"] > 0 and x["high"] >= pp["target"]:
                exit_price, why = pp["target"], "Target"
            elif pp["side"] < 0 and x["high"] >= pp["stop"]:
                exit_price, why = pp["stop"], "Stop"
            elif pp["side"] < 0 and x["low"] <= pp["target"]:
                exit_price, why = pp["target"], "Target"
            if exit_price is not None:
                self.journal.add(mode="paper",
                                 side="sell" if pp["side"] > 0 else "buy",
                                 lots=pp["lots"], entry=pp["entry"],
                                 exit=exit_price, strategy=self.config["strategy"],
                                 reason=f"Yahoo paper exit: {why}",
                                 raw={"symbol": self.symbol})
                self._log({"type": "exit", "side": pp["side"], "lots": pp["lots"],
                           "price": exit_price, "bar": bar, "reason": why})
                self._paper_position = None
                self.state["status"] = "scanning"
                return
            self.state["status"] = "in_position"
            return

        self.state["pyramid_count"] = 0
        side, reason = _signal(self.config["strategy"], candles, len(candles) - 1, {}, ind)
        self.state["signal"] = {"side": side, "reason": reason, "bar": bar}
        if side == 0:
            self.state["status"] = "scanning"
            return

        self._log({"type": "signal", "side": side, "reason": reason, "bar": bar})

        # Paper trade execution
        price = await self._get_yahoo_price()
        if price <= 0:
            self.state["error"] = "Could not fetch price"
            return

        av = ind["av"]
        dist = max(av[-1] * self.config["atr_stop"], 0.1)
        equity = 10000.0
        size = position_size(self.config["sizer"], equity,
                             self.config["risk_pct"], dist, price, state={})
        size = round(min(max(size, 0.01), self.max_lot), 2)

        stop = price - dist * side
        target = price + dist * self.config["rr"] * side

        self.state["trades"] += 1
        self.state["status"] = "in_position"
        self.state["error"] = None
        self._paper_position = {"side": side, "entry": price, "stop": stop,
                                "target": target, "lots": size, "bar": bar}
        self.journal.add(mode="paper", side="buy" if side == 1 else "sell",
                         lots=size, entry=price,
                         strategy=self.config["strategy"],
                         reason=f"Yahoo paper: {reason}",
                         raw={"symbol": self.symbol, "stop": stop, "target": target})
        self._log({"type": "entry", "side": side, "lots": size, "price": price,
                    "bar": bar, "stop": stop, "target": target, "ticket": f"PAPER-{bar}"})
        logger.info("[%s] PAPER %s %s @ %.4f SL=%.4f TP=%.4f",
                    self.symbol, "BUY" if side == 1 else "SELL",
                    size, price, stop, target)

    # ── Main engine step ──────────────────────────────────────────────────
    async def _step(self):
        if not self.config["enabled"]:
            self.state["status"] = "disabled"
            return
        if not self.live_enabled:
            self.state["status"] = "paper_only"
            return
        if not self._mt5_ready["ok"] or not self.mt5:
            self.state["status"] = "mt5_offline"
            return

        # Verify symbol is visible in MT5
        sym_info = await asyncio.to_thread(self.mt5.symbol_info, self.symbol)
        if sym_info is None:
            self.state["status"] = "symbol_unavailable"
            return
        if not sym_info.visible:
            await asyncio.to_thread(self.mt5.symbol_select, self.symbol, True)

        tf = self.mt5_timeframes.get(self.config["timeframe"])
        if tf is None:
            self.state["error"] = f"Unknown timeframe {self.config['timeframe']}"
            return
        rates = await asyncio.to_thread(self.mt5.copy_rates_from_pos, self.symbol, tf, 0, 320)
        if rates is None or not len(rates):
            if self.symbol in PROTECTED_SYMBOLS:
                # keep last status for protected symbols, don't stall
                self.state["status"] = self.state.get("status", "scanning")
                return
            self.state["status"] = "no_data"
            return
        candles = [{"time": int(r["time"]), "open": float(r["open"]),
                     "high": float(r["high"]), "low": float(r["low"]),
                     "close": float(r["close"]),
                     "volume": float(r["tick_volume"])} for r in rates]
        bar = candles[-1]["time"]
        if self.state["last_bar"] == bar:
            return
        self.state["last_bar"] = bar
        # Protected symbols never auto-halt
        if self.risk.halted and self.symbol not in PROTECTED_SYMBOLS:
            self.state["status"] = "halted"
            return
        from engine import indicators, signal as _signal, position_size
        ind = indicators(candles)
        open_rows = list(await asyncio.to_thread(self.mt5.positions_get, symbol=self.symbol) or [])
        ours = [p for p in open_rows if p.magic == self.magic]
        if ours:
            self.state["status"] = "in_position"
            await self._try_pyramid(candles, ind, ours, open_rows, bar)
            return
        self.state["pyramid_count"] = 0
        side, reason = _signal(self.config["strategy"], candles, len(candles) - 1, {}, ind)
        self.state["signal"] = {"side": side, "reason": reason, "bar": bar}
        if side == 0:
            self.state["status"] = "scanning"
            return
        self._log({"type": "signal", "side": side, "reason": reason, "bar": bar})

        kronos_check = self._kronos_agrees(side)
        self.state["signal"]["kronos"] = kronos_check
        if not kronos_check["ok"]:
            self.state["status"] = "kronos_veto"
            self.state["error"] = kronos_check["reason"]
            self._log({"type": "kronos_veto", "side": side,
                       "reason": kronos_check["reason"], "bar": bar})
            return
        if kronos_check["confidence"] > 0:
            self._log({"type": "kronos_confirm", "side": side,
                       "reason": kronos_check["reason"], "bar": bar})

        account = await asyncio.to_thread(self.mt5.account_info)
        if account is None:
            self.state["error"] = "Account info unavailable"
            return
        av = ind["av"]
        dist = max(av[-1] * self.config["atr_stop"], 0.1)
        size = position_size(self.config["sizer"], float(account.equity),
                             self.config["risk_pct"], dist, float(candles[-1]["close"]), state={})
        size = round(min(max(size, 0.01), self.max_lot), 2)
        exposure = sum(float(p.volume) for p in open_rows)
        decision = self.risk.check(size, len(open_rows), exposure, 0.0)
        if not decision["allowed"]:
            self.state["error"] = "; ".join(decision["reasons"])
            self.state["status"] = "risk_blocked"
            self._log({"type": "blocked", "reasons": decision["reasons"], "bar": bar})
            return
        tick = await asyncio.to_thread(self.mt5.symbol_info_tick, self.symbol)
        if not tick:
            self.state["error"] = "No tick"
            return
        price = tick.ask if side == 1 else tick.bid
        stop = price - dist * side
        target = price + dist * self.config["rr"] * side
        order_type = self.mt5.ORDER_TYPE_BUY if side == 1 else self.mt5.ORDER_TYPE_SELL
        request = {"action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": size,
                   "type": order_type, "price": price, "sl": round(stop, 2),
                   "tp": round(target, 2), "deviation": 20, "magic": self.magic,
                   "comment": "AuricEngine", "type_time": self.mt5.ORDER_TIME_GTC,
                   "type_filling": self.mt5.ORDER_FILLING_IOC}
        result = await asyncio.to_thread(self.mt5.order_send, request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            self.state["error"] = f"MT5 rejected order: {getattr(result, 'comment', 'no response')}"
            self.state["status"] = "rejected"
            self._log({"type": "rejected", "reason": self.state["error"], "bar": bar})
            return
        self.state["trades"] += 1
        self.state["status"] = "in_position"
        self.state["error"] = None
        self.journal.add(mode="live", side="buy" if side == 1 else "sell", lots=size,
                         entry=result.price, strategy=self.config["strategy"],
                         reason=f"Engine {reason}", raw=dict(request))
        self._log({"type": "entry", "side": side, "lots": size, "price": result.price,
                    "bar": bar, "ticket": result.order})
        dir_str = "LONG" if side == 1 else "SHORT"
        kronos_info = self.state.get("signal", {}).get("kronos", {})
        kronos_str = (f"\nKronos: dir={kronos_info.get('kronos_dir', '?')} "
                      f"conf={kronos_info.get('confidence', 0):.2f}") if kronos_info else ""
        await self.tg_notify(
            f"<b>Auric ENTRY</b> {dir_str} {self.symbol}\n"
            f"Lots: {size} | Price: {result.price}\n"
            f"SL: {round(stop, 2)} | TP: {round(target, 2)}\n"
            f"Strategy: {self.config['strategy']}{kronos_str}\n"
            f"Ticket: {result.order}")

    # ── Background loops ──────────────────────────────────────────────────
    async def run_engine_loop(self):
        while True:
            try:
                if self._mt5_ready["ok"] and self.mt5:
                    await self._trail()
                    await self._step()
                else:
                    await self._step_yahoo()
            except Exception as exc:
                self.state["error"] = str(exc)
                logger.warning("[%s] engine error: %s", self.symbol, exc)
            await asyncio.sleep(3)

    async def run_kronos_loop(self):
        for _ in range(60):
            if self._mt5_ready["ok"]:
                break
            await asyncio.sleep(2)

        while True:
            try:
                if self.kronos_ok:
                    candles = None
                    if self._mt5_ready["ok"] and self.mt5:
                        tf = self.mt5_timeframes.get(self.config["timeframe"])
                        if tf:
                            rates = await asyncio.to_thread(
                                self.mt5.copy_rates_from_pos, self.symbol, tf,
                                0, self.kronos_lookback + 50)
                            if rates is not None and len(rates) >= self.kronos_lookback + 1:
                                candles = [
                                    {"time": int(r["time"]), "open": float(r["open"]),
                                     "high": float(r["high"]), "low": float(r["low"]),
                                     "close": float(r["close"]),
                                     "volume": float(r["tick_volume"])}
                                    for r in rates
                                ]
                    else:
                        candles = await self._fetch_yahoo_candles()
                        if len(candles) < self.kronos_lookback + 1:
                            candles = None

                    if candles:
                        result = await asyncio.to_thread(
                            self.kronos_engine.forecast_from_candles,
                            candles,
                            lookback=self.kronos_lookback,
                            pred_len=self.kronos_pred_len,
                            model_id=self.kronos_model_id,
                            sample_count=2,
                        )
                        self.kronos_cache.update({
                            "direction": result["direction"],
                            "confidence": result["confidence"],
                            "pct_change": result["metadata"]["pct_change"],
                            "forecast_close": result["metadata"]["forecast_close"],
                            "last_close": result["metadata"]["last_close"],
                            "timestamp": int(time.time() * 1000),
                            "error": None,
                            "model": self.kronos_model_id,
                        })
                        logger.info("[%s] Kronos: dir=%s conf=%.2f pct=%.2f%%",
                                    self.symbol, result["direction"],
                                    result["confidence"],
                                    result["metadata"]["pct_change"])
            except Exception as exc:
                self.kronos_cache["error"] = str(exc)
                logger.warning("[%s] Kronos error: %s", self.symbol, exc)

            await asyncio.sleep(self.kronos_poll)

    def start(self):
        self._task_engine = asyncio.create_task(self.run_engine_loop())
        self._task_kronos = asyncio.create_task(self.run_kronos_loop())
        logger.info("[%s] engine + Kronos loops started", self.symbol)

    def stop(self):
        if self._task_engine:
            self._task_engine.cancel()
        if self._task_kronos:
            self._task_kronos.cancel()
        logger.info("[%s] engine + Kronos loops stopped", self.symbol)

    # ── Enable / disable per symbol ───────────────────────────────────────
    def enable(self):
        self.config["enabled"] = True
        self.state["status"] = "starting"
        self.state["error"] = None

    def disable(self):
        self.config["enabled"] = False
        self.state["status"] = "stopped"

    def reset_risk(self):
        self.risk.halted = False
        self.state["error"] = None

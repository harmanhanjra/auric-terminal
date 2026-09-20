"""Multi-symbol engine — runs independent engine loops + Kronos forecasts per symbol.

Each symbol gets its own config, state, Kronos cache, and risk check.
The server.py endpoints read from ENGINES dict to serve per-symbol status.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from mt5_data import checked_tick, checked_bars
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List

from execution_v2 import (
    normalize_price,
    spec_from_info,
)

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

SYMBOL_PROPS: Dict[str, Dict[str, Any]] = {
    "XAUUSD":  {"digits": 2, "point": 0.01,  "category": "metals", "contract_size": 100.0},
    "BTCUSD":  {"digits": 2, "point": 0.01,  "category": "crypto", "contract_size": 1.0},
    "EURUSD":  {"digits": 5, "point": 1e-5,  "category": "forex", "contract_size": 100000.0},
}


class SymbolEngine:
    """Self-contained engine instance for one trading symbol."""

    def __init__(self, symbol: str, mt5_mod, mt5_ready_ref: dict,
                 magic: int, live_enabled: bool, max_lot: float,
                 max_daily_loss: float, journal, tg_notify_fn,
                 kronos_engine_mod, kronos_ok: bool, mt5_timeframes: dict,
                 engine_mod, trade_guard_fn=None, paper_enabled: bool = True, executor=None):
        self.executor = executor
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
        self.trade_guard = trade_guard_fn
        self.paper_enabled = paper_enabled

        # Per-symbol engine config (all symbols share same defaults)
        self.config: Dict[str, Any] = {
            "enabled": os.getenv("ENGINE_ENABLED", "true").lower() == "true",
            "strategy": os.getenv("ENGINE_STRATEGY", "ema144_pullback"),
            "timeframe": os.getenv("ENGINE_TIMEFRAME", "M15"),
            "risk_pct": min(float(os.getenv("ENGINE_RISK_PCT", "0.5")), float(os.getenv("MAX_TRADE_RISK_PCT", "0.5"))),
            "sizer": "fixed_fractional",
            "atr_stop": float(os.getenv("ENGINE_ATR_STOP", "1.5")),
            "rr": float(os.getenv("ENGINE_RR", "2")),
            "trail_atr": float(os.getenv("ENGINE_TRAIL_ATR", "1.0")),
            "confirm_min": int(os.getenv("ENGINE_CONFIRM_MIN", "3")),
            "pyramid_frac": float(os.getenv("ENGINE_PYRAMID_FRAC", "0.5")),
            "max_pyramid": 0,
        }

        self.state: Dict[str, Any] = {
            "running": False, "last_bar": None, "signal": None,
            "error": None, "trades": 0, "status": "stopped",
            "log": [], "pyramid_count": 0,
            "effective_strategy": None, "regime": None,
        }

        self.kronos_cache: Dict[str, Any] = {
            "direction": 0, "confidence": 0.0, "pct_change": 0.0,
            "forecast_close": 0.0, "last_close": 0.0,
            "timestamp": 0, "error": None,
            "model": os.getenv("KRONOS_MODEL", "mini"),
        }

        # Per-symbol risk manager
        from engine import RiskManager
        default_spread = {"XAUUSD": 80.0, "BTCUSD": 1500.0, "EURUSD": 30.0}.get(symbol, 80.0)
        self.max_spread_points = float(
            os.getenv(f"MAX_SPREAD_POINTS_{symbol}", os.getenv("MAX_SPREAD_POINTS", str(default_spread)))
        )
        self.risk = RiskManager(
            daily_loss=max_daily_loss,
            max_lot=max_lot,
            spread_guard=self.max_spread_points,
        )

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
        running = (self.live_enabled and self.config["enabled"]
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
            "effectiveStrategy": self.state.get("effective_strategy"),
            "regime": self.state.get("regime"),
            "signal": self.state["signal"],
            "error": self.state["error"],
            "trades": self.state["trades"],
            "log": list(self.state["log"]),
            "pyramids": self.state["pyramid_count"],
            "config": {
                "risk_pct": self.config["risk_pct"],
                "atr_stop": self.config["atr_stop"],
                "rr": self.config["rr"],
                "trail_atr": self.config["trail_atr"],
                "confirm_min": self.config["confirm_min"],
                "pyramid_frac": self.config["pyramid_frac"],
                "max_pyramid": self.config["max_pyramid"],
                "autoLive": self.live_enabled,
                "paperExecution": self.paper_enabled,
            },
            "risk": {
                "halted": self.risk.halted,
                "realized": round(self.risk.realized, 2),
                "dailyLoss": self.max_daily_loss,
                "maxSpreadPoints": self.max_spread_points,
            },
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

    def _resolve_strategy(self, candles, ind) -> str:
        """Return the strategy for this bar, selecting by regime when set to auto."""
        configured = self.config["strategy"]
        if configured != "auto":
            self.state["effective_strategy"] = configured
            self.state["regime"] = None
            return configured
        from regime import select_strategy
        pool = [s.strip() for s in os.getenv("ENGINE_AUTO_POOL", "").split(",") if s.strip()]
        strategy_id, regime = select_strategy(candles, ind, pool=pool or None)
        previous = self.state.get("effective_strategy")
        self.state["effective_strategy"] = strategy_id
        self.state["regime"] = regime
        if previous and previous != strategy_id:
            self._log({"type": "strategy_switch", "from": previous,
                       "to": strategy_id, "regime": regime["regime"],
                       "bar": candles[-1]["time"]})
        return strategy_id

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
        if not self.kronos_ok or age_s > self.kronos_poll * 5 or self.kronos_cache["error"]:
            return {"ok": False, "reason": "Kronos confirmation unavailable or stale",
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

    def _external_trade_guard(self) -> dict:
        if not self.trade_guard:
            return {"allowed": True, "reason": "No external guard configured"}
        try:
            result = self.trade_guard(self.symbol)
            return result if isinstance(result, dict) else {"allowed": bool(result), "reason": "external guard"}
        except Exception as exc:
            return {"allowed": False, "reason": f"External trade guard error: {exc}"}

    async def _sync_realized(self):
        """Refresh today's realized P/L for this strategy/symbol from broker history."""
        if not self._mt5_ready["ok"] or not self.mt5:
            return
        now = datetime.now(timezone.utc)
        start = datetime.combine(now.date(), dtime.min, tzinfo=timezone.utc)
        deals = await asyncio.to_thread(self.mt5.history_deals_get, start, now) or []
        self.risk.realized = sum(
            float(getattr(d, "profit", 0.0) or 0.0)
            + float(getattr(d, "commission", 0.0) or 0.0)
            + float(getattr(d, "swap", 0.0) or 0.0)
            + float(getattr(d, "fee", 0.0) or 0.0)
            for d in deals
            if getattr(d, "magic", None) == self.magic
            and getattr(d, "symbol", None) == self.symbol
        )

    # ── Trailing stop ─────────────────────────────────────────────────────
    async def _trail(self):
        if not self.live_enabled or not self._mt5_ready["ok"] or not self.mt5:
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
        rates = await asyncio.to_thread(self.mt5.copy_rates_from_pos, self.symbol, tf, 0, 41)
        if rates is None or len(rates) < 16:
            return
        # Ignore the still-forming bar for all volatility calculations.
        closed = rates[:-1]
        candles = [{"open": float(r["open"]), "high": float(r["high"]),
                    "low": float(r["low"]), "close": float(r["close"])} for r in closed]
        av = _atr(candles, 14)
        info = await asyncio.to_thread(self.mt5.symbol_info, self.symbol)
        if info is None:
            return
        spec = spec_from_info(self.symbol, info)
        trail = max(av[-1] * self.config["trail_atr"],
                    max(info.trade_stops_level, info.trade_freeze_level) * spec.point + 2 * spec.tick_size)
        tick = await asyncio.to_thread(self.mt5.symbol_info_tick, self.symbol)
        if not tick:
            return
        try:
            checked_tick(tick)
        except ValueError:
            # Stale/invalid quote (e.g. market closed): skip trailing this cycle
            # instead of error-looping the engine task every few seconds.
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
                if current_sl == 0.0 or new_sl < current_sl - 0.3 * av[-1]:
                    moved = new_sl
            if moved is not None:
                sl = normalize_price(moved, spec)
                request = {"action": self.mt5.TRADE_ACTION_SLTP, "symbol": self.symbol,
                           "position": p.ticket, "sl": sl,
                           "tp": float(p.tp or 0.0), "type_time": self.mt5.ORDER_TIME_GTC}
                result = await asyncio.to_thread(self.mt5.order_send, request)
                if result and result.retcode == self.mt5.TRADE_RETCODE_DONE:
                    self._log({"type": "trail", "side": 1 if is_long else -1,
                               "sl": sl, "ticket": p.ticket})

    # ── Pyramiding ────────────────────────────────────────────────────────
    async def _step(self):
        """Evaluate the last CLOSED candle and, when armed, submit a guarded live order."""
        if not self.config["enabled"]:
            self.state["status"] = "disabled"
            return
        if not self._mt5_ready["ok"] or not self.mt5:
            self.state["status"] = "mt5_offline"
            return
        await self._sync_realized()
        if self.risk.realized <= -self.max_daily_loss:
            self.risk.kill()
        if self.risk.halted:
            self.state["status"] = "halted"
            return

        info = await asyncio.to_thread(self.mt5.symbol_info, self.symbol)
        if info is None:
            self.state["status"] = "symbol_unavailable"
            return
        if not info.visible:
            await asyncio.to_thread(self.mt5.symbol_select, self.symbol, True)
            info = await asyncio.to_thread(self.mt5.symbol_info, self.symbol)
        spec = spec_from_info(self.symbol, info)

        tf = self.mt5_timeframes.get(self.config["timeframe"])
        if tf is None:
            self.state["error"] = f"Unknown timeframe {self.config['timeframe']}"
            return
        rates = await asyncio.to_thread(self.mt5.copy_rates_from_pos, self.symbol, tf, 0, 321)
        if rates is None or len(rates) < 212:
            self.state["status"] = "no_data"
            return
        # MT5 position 0 is the forming candle. It must never generate an entry.
        candles = checked_bars(rates[:-1])
        tick = await asyncio.to_thread(self.mt5.symbol_info_tick, self.symbol)
        checked_tick(tick)
        bar = candles[-1]["time"]
        seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                   "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}.get(self.config["timeframe"])
        if seconds is None or not seconds <= time.time() - bar <= seconds * 2 + 30:
            # Market closed (weekend/holiday) or clock skew: wait quietly.
            # Raising here would flap the engine to "blocked" every 3 seconds.
            self.state["status"] = "market_closed"
            return
        if self.state["last_bar"] == bar:
            return
        self.state["last_bar"] = bar

        from engine import indicators, signal as _signal
        ind = indicators(candles)
        rows = await asyncio.to_thread(self.mt5.positions_get, symbol=self.symbol)
        if rows is None:
            raise ValueError("MT5 positions unavailable")
        open_rows = list(rows)
        ours = [p for p in open_rows if p.magic == self.magic]
        if ours:
            self.state["status"] = "in_position"
            # One protected position per symbol; no risk-increasing pyramids.
            return

        self.state["pyramid_count"] = 0
        strategy_id = self._resolve_strategy(candles, ind)
        side, reason = _signal(strategy_id, candles, len(candles) - 1, {}, ind)
        self.state["signal"] = {"side": side, "reason": reason, "bar": bar,
                                "strategy": strategy_id,
                                "mode": "live_auto" if self.live_enabled else "shadow"}
        if side == 0:
            self.state["status"] = "scanning"
            return
        self._log({"type": "signal", "side": side, "reason": reason,
                   "strategy": strategy_id, "bar": bar})

        from trade_quality import assess_setup
        higher = {"M1": "M15", "M5": "H1", "M15": "H1", "M30": "H4",
                  "H1": "H4", "H4": "D1", "D1": "W1", "W1": "W1"}[self.config["timeframe"]]
        higher_tf = self.mt5_timeframes.get(higher)
        if higher_tf is None:
            raise ValueError("Higher-timeframe MT5 context unavailable")
        higher_rates = await asyncio.to_thread(self.mt5.copy_rates_from_pos, self.symbol, higher_tf, 1, 80)
        context = checked_bars(higher_rates, minimum=50)
        quality = assess_setup(candles, context, side, self.config["rr"], tick.ask - tick.bid)
        self.state["signal"]["quality"] = quality
        if not quality["allowed"]:
            self.state["status"] = "quality_blocked"
            self.state["error"] = quality["reason"]
            self._log({"type": "blocked", "reason": quality["reason"], "bar": bar})
            return

        external_guard = self._external_trade_guard()
        self.state["signal"]["externalGuard"] = external_guard
        if not external_guard["allowed"]:
            self.state["status"] = "blackout"
            self.state["error"] = external_guard["reason"]
            self._log({"type": "blocked", "side": side, "reason": external_guard["reason"], "bar": bar})
            return

        kronos_check = self._kronos_agrees(side)
        self.state["signal"]["kronos"] = kronos_check
        if not kronos_check["ok"]:
            self.state["status"] = "kronos_veto"
            self.state["error"] = kronos_check["reason"]
            self._log({"type": "kronos_veto", "side": side,
                       "reason": kronos_check["reason"], "bar": bar})
            return

        if not self.live_enabled:
            self.state["status"] = "shadow"
            self.state["error"] = "Signal evaluated on MT5 data; live execution is disarmed"
            return
        if self.executor is None:
            raise ValueError("Autonomous executor is not configured")
        distance = float(ind["av"][-1]) * self.config["atr_stop"]
        result = await self.executor.submit(self, side, distance, bar)
        self.state["trades"] += 1
        self.state["status"] = "in_position"
        self.state["error"] = None
        self._log({"type": "entry", "side": side, "lots": result.volume,
                   "price": result.price, "bar": bar, "ticket": result.order})

    # ── Background loops ──────────────────────────────────────────────────
    async def run_engine_loop(self):
        while True:
            try:
                if self._mt5_ready["ok"] and self.mt5:
                    await self._trail()
                    await self._step()
                else:
                    self.state["status"] = "mt5_offline" if not self._mt5_ready["ok"] else "disarmed"
                    self.state["error"] = "MT5 connection and autonomous execution stage required"
            except Exception as exc:
                self.state["error"] = str(exc)
                self.state["status"] = "blocked"
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
                        if tf is not None:
                            rates = await asyncio.to_thread(
                                self.mt5.copy_rates_from_pos, self.symbol, tf,
                                0, self.kronos_lookback + 50)
                            if rates is not None and len(rates) >= self.kronos_lookback + 1:
                                candles = [
                                    {"time": int(r["time"]), "open": float(r["open"]),
                                     "high": float(r["high"]), "low": float(r["low"]),
                                     "close": float(r["close"]),
                                     "volume": float(r["tick_volume"])}
                                    for r in rates[:-1]
                                ]


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

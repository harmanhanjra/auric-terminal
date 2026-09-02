"""AuricTerminal market-data and execution gateway.

Data-source priority: MT5 -> Twelve Data -> deterministic demo feed.
Real order execution is disabled unless ENABLE_LIVE_TRADING=true.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from engine import (STRATEGIES, SIZERS, Journal, RiskManager, atr, backtest,
                    indicators, monte_carlo, optimize, position_size, signal)

logger = logging.getLogger("auric")

ROOT = Path(__file__).parent
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
TD_SYMBOL = os.getenv("TWELVE_DATA_SYMBOL", "XAU/USD")
TD_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
SOURCE = os.getenv("MARKET_DATA_SOURCE", "auto").lower()
LIVE_ENABLED = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
LIVE_API_KEY = os.getenv("AURIC_LIVE_API_KEY", "")
MAX_LOT = float(os.getenv("MAX_LOT", "1.0"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "500.0"))

if LIVE_ENABLED:
    logger.warning(
        "ENABLE_LIVE_TRADING=true — live MT5 execution is enabled. Verify the "
        "account is a demo account and risk limits (MAX_LOT, MAX_DAILY_LOSS) "
        "are sane before trading real money.")

try:
    import MetaTrader5 as mt5  # Windows + installed MT5 terminal only
except ImportError:
    mt5 = None

MT5_TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
    "1min": mt5.TIMEFRAME_M1, "5min": mt5.TIMEFRAME_M5, "15min": mt5.TIMEFRAME_M15,
    "30min": mt5.TIMEFRAME_M30, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4,
    "1day": mt5.TIMEFRAME_D1, "1week": mt5.TIMEFRAME_W1,
} if mt5 is not None else {}

#: Intervals accepted by the /api/candles endpoint regardless of MT5 availability.
ALLOWED_INTERVALS = {
    "M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1",
    "1min", "5min", "15min", "30min", "1h", "4h", "1day", "1week",
}

clients: set[WebSocket] = set()
latest = {"symbol": SYMBOL, "bid": 0.0, "ask": 0.0, "price": 0.0, "spread": 0.0,
          "source": "connecting", "timestamp": int(time.time() * 1000)}
feed_task: asyncio.Task | None = None
mt5_ready = False
risk = RiskManager(daily_loss=MAX_DAILY_LOSS, max_lot=MAX_LOT)

def _require_live_auth(request: Request) -> None:
    """Fail closed for live mutations unless an explicit API key is configured."""
    if not LIVE_API_KEY:
        raise HTTPException(503, "Live execution requires AURIC_LIVE_API_KEY to be configured")
    supplied = request.headers.get("x-auric-key", "")
    if not supplied or not hmac.compare_digest(supplied, LIVE_API_KEY):
        raise HTTPException(401, "Invalid or missing live execution key")
journal = Journal(str(ROOT / "auric.db"))

MAGIC = 144021
ENGINE_CONFIG = {
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
ENGINE_STATE = {
    "running": False, "last_bar": None, "signal": None, "error": None,
    "trades": 0, "status": "stopped", "log": [], "pyramid_count": 0,
}
engine_task: asyncio.Task | None = None

# --- Kronos integration config -------------------------------------------------
KRONOS_CONFIRM = os.getenv("ENGINE_KRONOS_CONFIRM", "true").lower() == "true"
KRONOS_POLL_SECONDS = int(os.getenv("KRONOS_POLL_SECONDS", "120"))
KRONOS_LOOKBACK = int(os.getenv("KRONOS_LOOKBACK", "400"))
KRONOS_PRED_LEN = int(os.getenv("KRONOS_PRED_LEN", "60"))
KRONOS_MODEL_ID = os.getenv("KRONOS_MODEL", "mini")
KRONOS_VETO_THRESHOLD = float(os.getenv("KRONOS_VETO_THRESHOLD", "0.3"))
KRONOS_CACHE = {
    "direction": 0,       # 1 = bullish, -1 = bearish, 0 = neutral
    "confidence": 0.0,    # 0..1
    "pct_change": 0.0,    # predicted % change
    "forecast_close": 0.0,
    "last_close": 0.0,
    "timestamp": 0,       # epoch ms
    "error": None,
    "model": KRONOS_MODEL_ID,
}

# Telegram notification config
TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

async def tg_notify(text: str):
    """Send a Telegram message (fire-and-forget)."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
    except Exception as exc:
        logger.warning("Telegram notify failed: %s", exc)
kronos_task: asyncio.Task | None = None

# ── Multi-symbol engines ─────────────────────────────────────────────────────
from multi_engine import SymbolEngine, SYMBOLS as ALL_SYMBOLS, SYMBOL_PROPS
ENGINES: dict[str, SymbolEngine] = {}  # populated in lifespan()

class OrderRequest(BaseModel):
    side: Literal["buy", "sell"]
    lots: float = Field(gt=0, le=100)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    mode: Literal["paper", "live"] = "paper"
    symbol: str = SYMBOL
    client_order_id: str = Field(min_length=8, max_length=80)

class BacktestRequest(BaseModel):
    candles: list[dict]
    strategy: str = "ema144_pullback"
    params: dict = {}
    initial: float = 10000
    risk_pct: float = 1
    sizer: str = "fixed_fractional"
    spread: float = .18

class OptimizeRequest(BaseModel):
    candles: list[dict]
    strategy: str
    grid: dict[str, list]

class MonteRequest(BaseModel):
    trades: list[dict]
    runs: int = Field(default=1000, ge=100, le=5000)
    initial: float = 10000

class KronosRequest(BaseModel):
    dataset: str = Field(default="HK_ali_09988_kline_5min_all.csv")
    lookback: int = Field(default=400, ge=100, le=512)
    pred_len: int = Field(default=60, ge=1, le=512)
    model: str = Field(default="mini", pattern="^(mini|small|base)$")
    T: float = Field(default=1.0, gt=0, le=5)
    top_p: float = Field(default=0.9, gt=0, le=1)
    sample_count: int = Field(default=2, ge=1, le=10)


def _validate_candles(candles: list[dict], minimum: int = 220) -> list[dict]:
    """Reject malformed or too-short candle series with a 422."""
    if not isinstance(candles, list) or len(candles) < minimum:
        raise HTTPException(422, f"At least {minimum} candles are required")
    for idx, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise HTTPException(422, f"Candle {idx} is not an object")
        for key in ("open", "high", "low", "close"):
            value = candle.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(
                    422, f"Candle {idx} has a non-numeric '{key}' value")
    return candles

async def init_mt5() -> bool:
    global mt5_ready
    if not mt5 or SOURCE not in ("auto", "mt5"):
        return False
    kwargs = {}
    if os.getenv("MT5_LOGIN"):
        kwargs["login"] = int(os.environ["MT5_LOGIN"])
    if os.getenv("MT5_PASSWORD"):
        kwargs["password"] = os.environ["MT5_PASSWORD"]
    if os.getenv("MT5_SERVER"):
        kwargs["server"] = os.environ["MT5_SERVER"]
    mt5_ready = await asyncio.to_thread(mt5.initialize, **kwargs)
    if mt5_ready:
        for sym in ALL_SYMBOLS:
            await asyncio.to_thread(mt5.symbol_select, sym, True)
    return mt5_ready

async def mt5_tick():
    if not mt5_ready:
        return None
    tick = await asyncio.to_thread(mt5.symbol_info_tick, SYMBOL)
    if not tick:
        return None
    bid, ask = float(tick.bid), float(tick.ask)
    return {"symbol": SYMBOL, "bid": bid, "ask": ask, "price": (bid + ask) / 2,
            "spread": ask - bid, "source": "MT5", "timestamp": int(tick.time_msc)}

async def twelve_data_tick(client: httpx.AsyncClient):
    if not TD_KEY or SOURCE not in ("auto", "web", "twelvedata"):
        return None
    response = await client.get("https://api.twelvedata.com/price",
                                params={"symbol": TD_SYMBOL, "apikey": TD_KEY}, timeout=8)
    payload = response.json()
    if "price" not in payload:
        raise RuntimeError(payload.get("message", "Twelve Data returned no price"))
    price = float(payload["price"])
    return {"symbol": SYMBOL, "bid": price, "ask": price, "price": price,
            "spread": 0.0, "source": "Twelve Data", "timestamp": int(time.time() * 1000)}

async def broadcast(data: dict):
    stale = []
    message = json.dumps({"type": "tick", **data})
    for ws in tuple(clients):
        try:
            await ws.send_text(message)
        except Exception:
            stale.append(ws)
    for ws in stale:
        clients.discard(ws)

async def market_loop():
    global latest
    # demo per symbol
    demos = {sym: 5000.0 for sym in ALL_SYMBOLS}
    async with httpx.AsyncClient() as client:
        await init_mt5()
        while True:
            overall_latest = {}
            for sym in ALL_SYMBOLS:
                tick = None
                try:
                    if mt5_ready and mt5:
                        # try direct tick from MT5 for this symbol
                        t = await asyncio.to_thread(mt5.symbol_info_tick, sym)
                        if t:
                            bid, ask = float(t.bid), float(t.ask)
                            tick = {"symbol": sym, "bid": bid, "ask": ask, "price": (bid + ask) / 2,
                                    "spread": ask - bid, "source": "MT5", "timestamp": int(t.time_msc)}
                except Exception:
                    pass
                if tick is None:
                    # Twelve Data only for primary symbol mapping
                    if sym == SYMBOL:
                        try:
                            tick = await twelve_data_tick(client)
                        except Exception:
                            pass
                if tick is None:
                    demo_price = demos[sym]
                    demo_price = max(1, demo_price + random.uniform(-0.45, 0.45))
                    demos[sym] = demo_price
                    tick = {"symbol": sym, "bid": demo_price - 0.09, "ask": demo_price + 0.09,
                            "price": demo_price, "spread": 0.18, "source": "Demo",
                            "timestamp": int(time.time() * 1000)}
                overall_latest[sym] = tick
                await broadcast(tick)
            latest = overall_latest.get(SYMBOL, {"symbol": SYMBOL, "source": "none"})
            await asyncio.sleep(0.5)

def engine_snapshot():
    running = (ENGINE_CONFIG["enabled"]
               and ENGINE_STATE["status"] not in ("stopped", "disabled",
                                                   "mt5_offline", "halted",
                                                   "no_data"))
    return {
        "running": running,
        "enabled": ENGINE_CONFIG["enabled"],
        "strategy": ENGINE_CONFIG["strategy"],
        "timeframe": ENGINE_CONFIG["timeframe"],
        "status": ENGINE_STATE["status"],
        "lastBar": ENGINE_STATE["last_bar"],
        "signal": ENGINE_STATE["signal"],
        "error": ENGINE_STATE["error"],
        "trades": ENGINE_STATE["trades"],
        "log": list(ENGINE_STATE["log"]),
        "pyramids": ENGINE_STATE["pyramid_count"],
        "config": {k: ENGINE_CONFIG[k] for k in
                   ("trail_atr", "confirm_min", "pyramid_frac", "max_pyramid")},
        "risk": {"halted": risk.halted, "realized": round(risk.realized, 2),
                 "dailyLoss": MAX_DAILY_LOSS},
        "kronos": {
            "enabled": KRONOS_CONFIRM,
            "available": KRONOS_OK,
            "direction": KRONOS_CACHE["direction"],
            "confidence": KRONOS_CACHE["confidence"],
            "pctChange": KRONOS_CACHE["pct_change"],
            "forecastClose": KRONOS_CACHE["forecast_close"],
            "lastClose": KRONOS_CACHE["last_close"],
            "model": KRONOS_CACHE["model"],
            "ageSeconds": round((time.time() * 1000 - KRONOS_CACHE["timestamp"]) / 1000, 1)
                          if KRONOS_CACHE["timestamp"] else None,
            "error": KRONOS_CACHE["error"],
        },
    }

def _engine_log(entry):
    entry["ts"] = int(time.time() * 1000)
    ENGINE_STATE["log"].insert(0, entry)
    del ENGINE_STATE["log"][60:]

async def update_realized():
    if not mt5_ready or not mt5:
        return
    start = datetime.combine(datetime.now().date(), dtime.min)
    deals = await asyncio.to_thread(mt5.history_deals_get, start, datetime.now()) or []
    risk.realized = sum(float(d.profit or 0.0) for d in deals if d.magic == MAGIC)

def confirmations(candles, ind=None):
    bull = bear = 0
    for sid, _, _ in STRATEGIES:
        s, _ = signal(sid, candles, len(candles) - 1, {}, ind)
        bull += int(s > 0)
        bear += int(s < 0)
    return {"bull": bull, "bear": bear}

async def modify_sl(ticket, sl, tp):
    if not mt5_ready or not mt5:
        return False
    request = {"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL, "position": ticket,
               "sl": sl, "tp": float(tp or 0.0), "type_time": mt5.ORDER_TIME_GTC}
    result = await asyncio.to_thread(mt5.order_send, request)
    return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

async def engine_trail():
    if not ENGINE_CONFIG["enabled"] or not mt5_ready or not mt5:
        return
    if not LIVE_ENABLED:
        ENGINE_STATE["status"] = "paper_only"
        return
    if ENGINE_CONFIG["trail_atr"] <= 0:
        return
    ours = [p for p in (list(await asyncio.to_thread(mt5.positions_get, symbol=SYMBOL) or []))
            if p.magic == MAGIC]
    if not ours:
        return
    tf = MT5_TIMEFRAMES.get(ENGINE_CONFIG["timeframe"])
    if tf is None:
        return
    rates = await asyncio.to_thread(mt5.copy_rates_from_pos, SYMBOL, tf, 0, 40)
    if rates is None or not len(rates):
        return
    candles = [{"open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"])} for r in rates]
    av = atr(candles, 14)
    trail = max(av[-1] * ENGINE_CONFIG["trail_atr"], 0.1)
    tick = await asyncio.to_thread(mt5.symbol_info_tick, SYMBOL)
    if not tick:
        return
    for p in ours:
        is_long = p.type == mt5.POSITION_TYPE_BUY
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
        if moved is not None and await modify_sl(p.ticket, round(moved, 2), p.tp):
            _engine_log({"type": "trail", "side": 1 if is_long else -1,
                         "sl": round(moved, 2), "ticket": p.ticket})

async def try_pyramid(candles, ind, ours, open_rows, bar):
    if ENGINE_CONFIG["confirm_min"] <= 0 or ENGINE_CONFIG["max_pyramid"] <= 0:
        return
    pos = ours[0]
    is_long = pos.type == mt5.POSITION_TYPE_BUY
    base = float(pos.volume)
    count = int(ENGINE_STATE.get("pyramid_count", 0))
    if count >= ENGINE_CONFIG["max_pyramid"]:
        return
    conf = confirmations(candles, ind)
    net = conf["bull"] - conf["bear"]
    strong = (is_long and net >= ENGINE_CONFIG["confirm_min"]) or \
             (not is_long and -net >= ENGINE_CONFIG["confirm_min"])
    if not strong:
        return

    # --- Kronos must also agree before pyramiding ----------------------------
    pyramid_side = 1 if is_long else -1
    kronos_check = _kronos_agrees(pyramid_side)
    if not kronos_check["ok"]:
        _engine_log({"type": "kronos_veto", "side": pyramid_side,
                     "reason": f"Pyramid blocked: {kronos_check['reason']}",
                     "bar": bar})
        return

    total_volume = sum(float(o.volume) for o in open_rows)
    add = round(min(base * ENGINE_CONFIG["pyramid_frac"], MAX_LOT), 2)
    if add < 0.01 or total_volume + add > MAX_LOT:
        return
    decision = risk.check(add, len(open_rows), total_volume, float(latest.get("spread", 0)))
    if not decision["allowed"]:
        ENGINE_STATE["error"] = "; ".join(decision["reasons"])
        _engine_log({"type": "blocked", "reasons": decision["reasons"], "bar": bar})
        return
    tick = await asyncio.to_thread(mt5.symbol_info_tick, SYMBOL)
    if not tick:
        return
    price = tick.ask if is_long else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL
    request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": add,
               "type": order_type, "price": price,
               "sl": float(pos.sl) if pos.sl else 0.0,
               "tp": float(pos.tp) if pos.tp else 0.0,
               "deviation": 20, "magic": MAGIC, "comment": "AuricEngine+",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
    result = await asyncio.to_thread(mt5.order_send, request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        ENGINE_STATE["error"] = f"MT5 rejected pyramid: {getattr(result, 'comment', 'no response')}"
        _engine_log({"type": "rejected", "reason": ENGINE_STATE["error"], "bar": bar})
        return
    ENGINE_STATE["pyramid_count"] = count + 1
    ENGINE_STATE["trades"] += 1
    ENGINE_STATE["error"] = None
    journal.add(mode="live", side="buy" if is_long else "sell", lots=add,
                entry=result.price, strategy=ENGINE_CONFIG["strategy"],
                reason=f"Engine pyramid (conf {net:+d})", raw=dict(request))
    _engine_log({"type": "pyramid", "side": 1 if is_long else -1, "lots": add,
                 "price": result.price, "bar": bar, "ticket": result.order,
                 "confirm": net})
    dir_str = "LONG" if is_long else "SHORT"
    await tg_notify(
        f"<b>Auric PYRAMID</b> {dir_str} {SYMBOL}\n"
        f"+{add} lots @ {result.price} (total vol: {total_volume + add})\n"
        f"Pyramid #{count + 1} | Ticket: {result.order}")

async def engine_step():
    if not ENGINE_CONFIG["enabled"]:
        ENGINE_STATE["status"] = "disabled"
        return
    if not LIVE_ENABLED:
        ENGINE_STATE["status"] = "paper_only"
        return
    if not mt5_ready or not mt5:
        ENGINE_STATE["status"] = "mt5_offline"
        return
    tf = MT5_TIMEFRAMES.get(ENGINE_CONFIG["timeframe"])
    if tf is None:
        ENGINE_STATE["error"] = f"Unknown timeframe {ENGINE_CONFIG['timeframe']}"
        return
    rates = await asyncio.to_thread(mt5.copy_rates_from_pos, SYMBOL, tf, 0, 320)
    if rates is None or not len(rates):
        ENGINE_STATE["status"] = "no_data"
        return
    candles = [{"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r["tick_volume"])} for r in rates]
    bar = candles[-1]["time"]
    if ENGINE_STATE["last_bar"] == bar:
        return
    ENGINE_STATE["last_bar"] = bar
    try:
        await update_realized()
    except Exception:
        pass
    if risk.halted:
        ENGINE_STATE["status"] = "halted"
        return
    ind = indicators(candles)
    open_rows = list(await asyncio.to_thread(mt5.positions_get, symbol=SYMBOL) or [])
    ours = [p for p in open_rows if p.magic == MAGIC]
    if ours:
        ENGINE_STATE["status"] = "in_position"
        await try_pyramid(candles, ind, ours, open_rows, bar)
        return
    ENGINE_STATE["pyramid_count"] = 0
    side, reason = signal(ENGINE_CONFIG["strategy"], candles, len(candles) - 1, {}, ind)
    ENGINE_STATE["signal"] = {"side": side, "reason": reason, "bar": bar}
    if side == 0:
        ENGINE_STATE["status"] = "scanning"
        return
    _engine_log({"type": "signal", "side": side, "reason": reason, "bar": bar})

    # --- Kronos AI confirmation for ALL strategies ---------------------------
    kronos_check = _kronos_agrees(side)
    ENGINE_STATE["signal"]["kronos"] = kronos_check
    if not kronos_check["ok"]:
        ENGINE_STATE["status"] = "kronos_veto"
        ENGINE_STATE["error"] = kronos_check["reason"]
        _engine_log({"type": "kronos_veto", "side": side,
                     "reason": kronos_check["reason"], "bar": bar})
        return
    if kronos_check["confidence"] > 0:
        _engine_log({"type": "kronos_confirm", "side": side,
                     "reason": kronos_check["reason"], "bar": bar})

    account = await asyncio.to_thread(mt5.account_info)
    if account is None:
        ENGINE_STATE["error"] = "Account info unavailable"
        return
    av = ind["av"]
    dist = max(av[-1] * ENGINE_CONFIG["atr_stop"], 0.1)
    size = position_size(ENGINE_CONFIG["sizer"], float(account.equity),
                         ENGINE_CONFIG["risk_pct"], dist, float(candles[-1]["close"]), state={})
    size = round(min(max(size, 0.01), MAX_LOT), 2)
    exposure = sum(float(p.volume) for p in open_rows)
    decision = risk.check(size, len(open_rows), exposure, float(latest.get("spread", 0)))
    if not decision["allowed"]:
        ENGINE_STATE["error"] = "; ".join(decision["reasons"])
        ENGINE_STATE["status"] = "risk_blocked"
        _engine_log({"type": "blocked", "reasons": decision["reasons"], "bar": bar})
        return
    tick = await asyncio.to_thread(mt5.symbol_info_tick, SYMBOL)
    if not tick:
        ENGINE_STATE["error"] = "No tick"
        return
    price = tick.ask if side == 1 else tick.bid
    stop = price - dist * side
    target = price + dist * ENGINE_CONFIG["rr"] * side
    order_type = mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL
    request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": size,
               "type": order_type, "price": price, "sl": round(stop, 2),
               "tp": round(target, 2), "deviation": 20, "magic": MAGIC,
               "comment": "AuricEngine", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
    result = await asyncio.to_thread(mt5.order_send, request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        ENGINE_STATE["error"] = f"MT5 rejected order: {getattr(result, 'comment', 'no response')}"
        ENGINE_STATE["status"] = "rejected"
        _engine_log({"type": "rejected", "reason": ENGINE_STATE["error"], "bar": bar})
        return
    ENGINE_STATE["trades"] += 1
    ENGINE_STATE["status"] = "in_position"
    ENGINE_STATE["error"] = None
    journal.add(mode="live", side="buy" if side == 1 else "sell", lots=size,
                entry=result.price, strategy=ENGINE_CONFIG["strategy"],
                reason=f"Engine {reason}", raw=dict(request))
    _engine_log({"type": "entry", "side": side, "lots": size, "price": result.price,
                 "bar": bar, "ticket": result.order})
    dir_str = "LONG" if side == 1 else "SHORT"
    kronos_info = ENGINE_STATE.get("signal", {}).get("kronos", {})
    kronos_str = f"\nKronos: dir={kronos_info.get('kronos_dir', '?')} conf={kronos_info.get('confidence', 0):.2f}" if kronos_info else ""
    await tg_notify(
        f"<b>Auric ENTRY</b> {dir_str} {SYMBOL}\n"
        f"Lots: {size} | Price: {result.price}\n"
        f"SL: {round(stop, 2)} | TP: {round(target, 2)}\n"
        f"Strategy: {ENGINE_CONFIG['strategy']}{kronos_str}\n"
        f"Ticket: {result.order}")

# ---------------------------------------------------------------------------
# Kronos background forecast — runs every KRONOS_POLL_SECONDS, caches result
# ---------------------------------------------------------------------------

async def kronos_forecast_loop():
    """Periodically forecast direction using Kronos on live MT5 candles."""
    global KRONOS_CACHE
    # wait for MT5 to be ready before first forecast
    for _ in range(60):
        if mt5_ready:
            break
        await asyncio.sleep(2)

    while True:
        try:
            if KRONOS_OK and mt5_ready and mt5:
                tf = MT5_TIMEFRAMES.get(ENGINE_CONFIG["timeframe"])
                if tf:
                    rates = await asyncio.to_thread(
                        mt5.copy_rates_from_pos, SYMBOL, tf, 0, KRONOS_LOOKBACK + 50)
                    if rates is not None and len(rates) >= KRONOS_LOOKBACK + 1:
                        candles = [
                            {"time": int(r["time"]), "open": float(r["open"]),
                             "high": float(r["high"]), "low": float(r["low"]),
                             "close": float(r["close"]),
                             "volume": float(r["tick_volume"])}
                            for r in rates
                        ]
                        result = await asyncio.to_thread(
                            kronos_engine.forecast_from_candles,
                            candles,
                            lookback=KRONOS_LOOKBACK,
                            pred_len=KRONOS_PRED_LEN,
                            model_id=KRONOS_MODEL_ID,
                            sample_count=2,
                        )
                        KRONOS_CACHE.update({
                            "direction": result["direction"],
                            "confidence": result["confidence"],
                            "pct_change": result["metadata"]["pct_change"],
                            "forecast_close": result["metadata"]["forecast_close"],
                            "last_close": result["metadata"]["last_close"],
                            "timestamp": int(time.time() * 1000),
                            "error": None,
                            "model": KRONOS_MODEL_ID,
                        })
                        logger.info(
                            "Kronos forecast: dir=%s conf=%.2f pct=%.2f%%",
                            result["direction"], result["confidence"],
                            result["metadata"]["pct_change"])
                        # Sync to multi-engine for primary symbol
                        if SYMBOL in ENGINES:
                            ENGINES[SYMBOL].kronos_cache.update(KRONOS_CACHE)
        except Exception as exc:
            KRONOS_CACHE["error"] = str(exc)
            logger.warning("Kronos forecast loop error: %s", exc)

        await asyncio.sleep(KRONOS_POLL_SECONDS)


def _kronos_agrees(side: int) -> dict:
    """Check whether the Kronos cached forecast agrees with a signal.

    Returns {"ok": bool, "reason": str, "kronos_dir": int, "confidence": float}.
    When KRONOS_CONFIRM is disabled or cache is stale, always returns ok=True.
    """
    if not KRONOS_CONFIRM:
        return {"ok": True, "reason": "Kronos confirmation disabled",
                "kronos_dir": 0, "confidence": 0.0}

    cache_age_s = (time.time() * 1000 - KRONOS_CACHE["timestamp"]) / 1000.0
    # if cache is older than 5× the poll interval, treat as stale / unknown
    if cache_age_s > KRONOS_POLL_SECONDS * 5 or KRONOS_CACHE["error"]:
        return {"ok": True, "reason": "Kronos cache stale — passing through",
                "kronos_dir": 0, "confidence": 0.0}

    k_dir = KRONOS_CACHE["direction"]
    conf = KRONOS_CACHE["confidence"]

    # neutral forecast never vetoes
    if k_dir == 0 or conf < KRONOS_VETO_THRESHOLD:
        return {"ok": True,
                "reason": f"Kronos neutral/low-conf (dir={k_dir} conf={conf:.2f})",
                "kronos_dir": k_dir, "confidence": conf}

    # direction mismatch → veto
    if k_dir != side:
        return {"ok": False,
                "reason": (f"Kronos VETO: signal {'LONG' if side==1 else 'SHORT'} "
                           f"but Kronos predicts {'DOWN' if k_dir==-1 else 'UP'} "
                           f"(conf {conf:.2f}, Δ{KRONOS_CACHE['pct_change']:+.2f}%)"),
                "kronos_dir": k_dir, "confidence": conf}

    # direction match → boost
    return {"ok": True,
            "reason": (f"Kronos CONFIRMED: dir={k_dir} conf={conf:.2f} "
                       f"Δ{KRONOS_CACHE['pct_change']:+.2f}%"),
            "kronos_dir": k_dir, "confidence": conf}


async def engine_loop():
    while True:
        try:
            await engine_trail()
            await engine_step()
        except Exception as exc:
            ENGINE_STATE["error"] = str(exc)
        await asyncio.sleep(3)

@asynccontextmanager
async def lifespan(_: FastAPI):
    global feed_task, engine_task, kronos_task, mt5_ready
    # Init MT5 first so symbols are selected
    await init_mt5()
    feed_task = asyncio.create_task(market_loop())
    engine_task = asyncio.create_task(engine_loop())
    kronos_task = asyncio.create_task(kronos_forecast_loop())

    # ── Start multi-symbol engines ────────────────────────────────────────
    mt5_ref = {"ok": mt5_ready}
    # Ensure MT5 ref is accurate immediately after init
    if mt5_ready:
        mt5_ref["ok"] = True

    # Patch mt5_ref when MT5 connects — use a simple polling wrapper
    async def _sync_mt5_ref():
        while True:
            if mt5_ready and not mt5_ref["ok"]:
                mt5_ref["ok"] = True
            await asyncio.sleep(2)
    asyncio.create_task(_sync_mt5_ref())

    for sym in ALL_SYMBOLS:
        if sym == SYMBOL:
            # For the primary symbol, reuse existing single-symbol state
            # but create a multi-engine wrapper for the /api/symbols endpoint
            eng = SymbolEngine(
                symbol=sym, mt5_mod=mt5, mt5_ready_ref=mt5_ref,
                magic=MAGIC, live_enabled=LIVE_ENABLED,
                max_lot=MAX_LOT, max_daily_loss=MAX_DAILY_LOSS,
                journal=journal, tg_notify_fn=tg_notify,
                kronos_engine_mod=kronos_engine, kronos_ok=KRONOS_OK,
                mt5_timeframes=MT5_TIMEFRAMES, engine_mod=None,
            )
            # Share state with the primary single-symbol engine
            eng.config.update(ENGINE_CONFIG)
            eng.state.update(ENGINE_STATE)
            eng.kronos_cache.update(KRONOS_CACHE)
        else:
            eng = SymbolEngine(
                symbol=sym, mt5_mod=mt5, mt5_ready_ref=mt5_ref,
                magic=MAGIC, live_enabled=LIVE_ENABLED,
                max_lot=MAX_LOT, max_daily_loss=MAX_DAILY_LOSS,
                journal=journal, tg_notify_fn=tg_notify,
                kronos_engine_mod=kronos_engine, kronos_ok=KRONOS_OK,
                mt5_timeframes=MT5_TIMEFRAMES, engine_mod=None,
            )
            eng.enable()
        ENGINES[sym] = eng

    # Start non-primary engines (primary already has engine_loop + kronos_forecast_loop)
    for sym, eng in ENGINES.items():
        if sym != SYMBOL and eng.config["enabled"]:
            eng.start()

    # Ensure all symbols are selected in MT5 immediately
    if mt5_ready and mt5:
        for sym in ALL_SYMBOLS:
            try:
                asyncio.create_task(asyncio.to_thread(mt5.symbol_select, sym, True))
            except Exception:
                pass

    logger.info("Multi-symbol engine started: %s", list(ENGINES.keys()))
    yield

    feed_task.cancel()
    if engine_task:
        engine_task.cancel()
    if kronos_task:
        kronos_task.cancel()
    for eng in ENGINES.values():
        eng.stop()
    if mt5_ready and mt5:
        mt5.shutdown()

app = FastAPI(title="AuricTerminal Gateway", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request, call_next):
    """Defense-in-depth response headers. CSP is loose because the terminal
    ships a self-contained UI; external assets are limited to Google Fonts."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'")
    return response


WEB_DIST = ROOT / "web" / "dist"


@app.get("/")
async def terminal():
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return FileResponse(ROOT / "index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "source": latest.get("source"), "liveTrading": LIVE_ENABLED,
            "symbol": SYMBOL, "timestamp": int(time.time() * 1000)}

@app.get("/api/quote")
async def quote():
    return latest

@app.get("/api/strategies")
async def strategies():
    return {"strategies": [{"id": i, "name": n, "category": c} for i, n, c in STRATEGIES],
            "positionSizing": SIZERS}

@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest):
    if req.strategy not in {x[0] for x in STRATEGIES}:
        raise HTTPException(422, "Unknown strategy")
    if req.sizer not in SIZERS:
        raise HTTPException(422, "Unknown position-sizing method")
    _validate_candles(req.candles)
    return await asyncio.to_thread(backtest, req.candles, req.strategy, req.params,
                                   req.initial, req.risk_pct, req.sizer, req.spread)

@app.post("/api/optimize")
async def run_optimize(req: OptimizeRequest):
    _validate_candles(req.candles)
    combinations = 1
    for values in req.grid.values(): combinations *= len(values)
    if combinations > 250:
        raise HTTPException(422, "Optimization grid is limited to 250 combinations")
    return {"runs": await asyncio.to_thread(optimize, req.candles, req.strategy, req.grid)}

@app.post("/api/monte-carlo")
async def run_monte(req: MonteRequest):
    return await asyncio.to_thread(monte_carlo, req.trades, req.runs, req.initial)

@app.get("/api/journal")
async def get_journal(limit: int = 200):
    """Trade journal — returns entries with backward-compat alias."""
    capped = max(1, min(limit, 1000))
    entries = journal.list(capped)
    return {"entries": entries, "trades": entries}

@app.get("/api/engine")
async def engine_status():
    return engine_snapshot()

# ── Multi-symbol endpoints ────────────────────────────────────────────────
@app.get("/api/symbols")
async def list_symbols():
    """List all tracked symbols with their engine status."""
    return {"symbols": [ENGINES[s].snapshot() for s in ALL_SYMBOLS if s in ENGINES]}

@app.get("/api/symbols/{symbol}")
async def symbol_status(symbol: str):
    """Get engine status for a specific symbol."""
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked. Available: {list(ENGINES.keys())}")
    return ENGINES[sym].snapshot()


@app.get("/api/symbols/{symbol}/quote")
async def symbol_quote(symbol: str):
    """Return the latest normalized tick for the requested symbol.

    Uses MT5 when connected, falls back to the broadcast `latest` cache,
    and finally emits a deterministic demo tick so the header is always
    responsive. Source is always labelled honestly.
    """
    sym = symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked. Available: {ALL_SYMBOLS}")

    if mt5_ready and mt5:
        try:
            t = await asyncio.to_thread(mt5.symbol_info_tick, sym)
            if t:
                bid, ask = float(t.bid), float(t.ask)
                return {
                    "symbol": sym, "bid": bid, "ask": ask, "price": (bid + ask) / 2,
                    "spread": ask - bid, "source": "MT5",
                    "timestamp": int(getattr(t, "time_msc", time.time() * 1000)),
                }
        except Exception:
            pass

    cache = latest if isinstance(latest, dict) else {}
    if sym in cache and isinstance(cache[sym], dict) and cache[sym].get("source"):
        return cache[sym]

    seed = 4000.0 if sym == "XAUUSD" else (70000.0 if sym == "BTCUSD" else 1.0)
    base = 1.08 if sym == "EURUSD" else (1.27 if sym == "GBPUSD" else (149.0 if sym == "USDJPY" else seed))
    jitter = ((time.time() * 1000) % 1000) / 1000.0
    price = base + (jitter - 0.5) * (base * 0.0005)
    return {
        "symbol": sym, "bid": price - 0.05, "ask": price + 0.05, "price": price,
        "spread": 0.10, "source": "Demo", "timestamp": int(time.time() * 1000),
    }

@app.get("/api/symbols/{symbol}/trades")
async def symbol_trades(symbol: str, limit: int = 200):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    eng = ENGINES[sym]
    # SymbolEngine keeps trades count and log; return log entries
    log = eng.state.get("log", [])[-limit:]
    return {"symbol": sym, "trades": eng.state.get("trades", 0), "log": log}

@app.get("/api/symbols/{symbol}/metrics")
async def symbol_metrics(symbol: str):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    eng = ENGINES[sym]
    return {"symbol": sym, "metrics": {
        "trades": eng.state.get("trades", 0),
        "pyramids": eng.state.get("pyramid_count", 0),
        "status": eng.state.get("status"),
        "running": eng.state.get("running"),
    }}

@app.post("/api/symbols/{symbol}/start")
async def symbol_start(symbol: str):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    if not LIVE_ENABLED:
        raise HTTPException(403, "Live execution is disabled")
    eng = ENGINES[sym]
    eng.enable()
    if sym == SYMBOL:
        ENGINE_CONFIG["enabled"] = True
        ENGINE_STATE["status"] = "starting"
    return eng.snapshot()

@app.post("/api/symbols/{symbol}/stop")
async def symbol_stop(symbol: str):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    # Protected symbols cannot be stopped via API
    if sym in {"XAUUSD", "BTCUSD"}:
        raise HTTPException(403, f"Symbol {sym} is protected and cannot be stopped via API")
    eng = ENGINES[sym]
    eng.disable()
    if sym == SYMBOL:
        ENGINE_CONFIG["enabled"] = False
        ENGINE_STATE["status"] = "stopped"
    return eng.snapshot()

@app.get("/api/symbols/all/kronos")
async def all_kronos():
    """Get Kronos forecast for every symbol."""
    return {"symbols": {s: ENGINES[s].kronos_cache for s in ALL_SYMBOLS if s in ENGINES}}

@app.post("/api/engine/start")
async def engine_start():
    if not LIVE_ENABLED:
        raise HTTPException(403, "Live execution is disabled on the server")
    ENGINE_CONFIG["enabled"] = True
    ENGINE_STATE["status"] = "starting"
    ENGINE_STATE["error"] = None
    return engine_snapshot()

@app.post("/api/engine/stop")
async def engine_stop():
    ENGINE_CONFIG["enabled"] = False
    ENGINE_STATE["status"] = "stopped"
    return engine_snapshot()

@app.post("/api/engine/reset")
async def engine_reset():
    risk.halted = False
    ENGINE_STATE["error"] = None
    return engine_snapshot()

@app.get("/api/account")
async def account():
    if not mt5_ready or not mt5:
        return {"connected": False, "source": latest.get("source")}
    info = await asyncio.to_thread(mt5.account_info)
    if not info:
        raise HTTPException(503, "MT5 account information unavailable")
    return {"connected": True, "login": info.login, "balance": info.balance,
            "equity": info.equity, "margin": info.margin, "freeMargin": info.margin_free,
            "marginLevel": info.margin_level, "currency": info.currency}

@app.get("/api/positions")
async def positions(symbol: str | None = None):
    if not mt5_ready or not mt5:
        if symbol:
            return {"symbol": symbol.upper(), "positions": []}
        return {"positions": []}
    rows = await asyncio.to_thread(mt5.positions_get) or []
    ours = [p for p in rows if p.magic == MAGIC]
    if symbol:
        sym = symbol.upper()
        ours = [p for p in ours if p.symbol == sym]
        return {"symbol": sym, "positions": [{"ticket": p.ticket, "symbol": p.symbol,
                 "side": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                 "lots": p.volume, "entry": p.price_open, "market": p.price_current,
                 "sl": p.sl, "tp": p.tp, "pnl": p.profit} for p in ours]}
    return {"positions": [{"ticket": p.ticket, "symbol": p.symbol,
             "side": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
             "lots": p.volume, "entry": p.price_open, "market": p.price_current,
             "sl": p.sl, "tp": p.tp, "pnl": p.profit} for p in ours]}

@app.post("/api/risk/reset")
async def reset_risk():
    risk.halted = False
    return {"ok": True, "halted": False}

@app.get("/api/candles")
async def candles(symbol: str = SYMBOL, interval: str = "M15", outputsize: int = 300):
    sym = symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked. Available: {ALL_SYMBOLS}")
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(422, "Unsupported interval")
    outputsize = max(10, min(outputsize, 5000))
    tf = MT5_TIMEFRAMES.get(interval)
    if mt5_ready and mt5 and tf:
        rates = await asyncio.to_thread(mt5.copy_rates_from_pos, sym, tf, 0, outputsize)
        if rates is not None and len(rates):
            values = [{"time": int(r["time"]) * 1000, "open": float(r["open"]),
                       "high": float(r["high"]), "low": float(r["low"]),
                       "close": float(r["close"]), "volume": float(r["tick_volume"])}
                      for r in rates]
            return {"symbol": sym, "interval": interval, "source": "MT5", "values": values}
        raise HTTPException(502, "MT5 returned no candles for this symbol/timeframe")
    if not TD_KEY:
        raise HTTPException(503, "No market-data source available for historical candles")
    async with httpx.AsyncClient() as client:
        r = await client.get("https://api.twelvedata.com/time_series", params={
            "symbol": SYMBOL_PROPS.get(sym, {}).get("td_symbol", sym), "interval": interval, "outputsize": outputsize,
            "order": "ASC", "apikey": TD_KEY}, timeout=20)
    payload = r.json()
    if "values" not in payload:
        raise HTTPException(502, payload.get("message", "Market-data request failed"))
    values = [{"open": float(v["open"]), "high": float(v["high"]), "low": float(v["low"]),
               "close": float(v["close"]), "volume": float(v.get("volume", 0) or 0)}
              for v in payload["values"]]
    return {"symbol": sym, "interval": interval, "source": "Twelve Data", "values": values}

@app.websocket("/ws/market")
async def ws_market(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "tick", **latest})
    try:
        while True:
            await ws.receive_text()  # client heartbeat
    except WebSocketDisconnect:
        clients.discard(ws)

@app.post("/api/orders")
async def order(req: OrderRequest, request: Request):
    sym = req.symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    if req.lots > MAX_LOT:
        raise HTTPException(422, f"Lot size exceeds server risk limit ({MAX_LOT})")
    open_rows = []
    if mt5_ready and mt5:
        open_rows = list(await asyncio.to_thread(mt5.positions_get, symbol=sym) or [])
    # retrieve latest tick for this symbol from overall_latest
    ticks = latest if isinstance(latest, dict) and "symbol" not in latest else {}
    tick_info = ticks.get(sym, {})
    spread = float(tick_info.get("spread", 0))
    decision = risk.check(req.lots, len(open_rows), sum(float(p.volume) for p in open_rows), spread)
    if not decision["allowed"]:
        raise HTTPException(403, "; ".join(decision["reasons"]))
    if req.mode == "paper":
        # use demo/real tick price for this symbol
        price = tick_info.get("ask" if req.side == "buy" else "bid")
        if not price:
            # fallback to latest global
            price = latest.get("ask" if req.side == "buy" else "bid") if isinstance(latest, dict) and "ask" in latest else None
        if not price or price <= 0:
            raise HTTPException(503, "No market price available yet")
        journal.add(mode="paper", side=req.side, lots=req.lots, entry=price,
                    strategy="manual", reason="Order ticket", raw=req.model_dump())
        return {"accepted": True, "mode": "paper", "symbol": sym, "clientOrderId": req.client_order_id,
                "fillPrice": price, "source": tick_info.get("source", latest.get("source"))}
    if not LIVE_ENABLED:
        raise HTTPException(403, "Live execution is disabled on the server")
    _require_live_auth(request)
    if not mt5_ready or not mt5:
        raise HTTPException(503, "MT5 terminal is not connected")
    tick = await asyncio.to_thread(mt5.symbol_info_tick, sym)
    if tick is None:
        raise HTTPException(503, "No market tick available from MT5")
    order_type = mt5.ORDER_TYPE_BUY if req.side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if req.side == "buy" else tick.bid
    request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": req.lots,
               "type": order_type, "price": price, "sl": req.stop_loss or 0.0,
               "tp": req.take_profit or 0.0, "deviation": 20, "magic": MAGIC,
               "comment": f"Auric {req.client_order_id[:18]}", "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
    result = await asyncio.to_thread(mt5.order_send, request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise HTTPException(502, f"MT5 rejected order: {getattr(result, 'comment', 'unknown error')}")
    journal.add(mode="live", side=req.side, lots=req.lots, entry=result.price,
                strategy="manual", reason="MT5 market order", raw=req.model_dump())
    return {"accepted": True, "mode": "live", "symbol": sym, "ticket": result.order,
            "deal": result.deal, "fillPrice": result.price, "clientOrderId": req.client_order_id}

@app.post("/api/kill")
async def kill_all(request: Request, symbol: str = SYMBOL, mode: Literal["paper", "live"] = "paper"):
    sym = symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    risk.kill()
    if mode == "paper":
        journal.add(mode="paper", side="system", strategy="risk", reason=f"Kill switch activated for {sym}")
        return {"ok": True, "mode": "paper", "symbol": sym, "closed": 0, "cancelled": 0, "halted": True}
    if not LIVE_ENABLED:
        raise HTTPException(403, "Live execution is disabled on the server")
    _require_live_auth(request)
    if not mt5_ready or not mt5:
        raise HTTPException(503, "MT5 terminal is not connected")
    closed = cancelled = 0
    for pending in list(await asyncio.to_thread(mt5.orders_get, symbol=sym) or []):
        if getattr(pending, "magic", None) != MAGIC:
            continue
        result = await asyncio.to_thread(mt5.order_send, {"action": mt5.TRADE_ACTION_REMOVE,
                                                           "order": pending.ticket})
        cancelled += int(bool(result and result.retcode == mt5.TRADE_RETCODE_DONE))
    for p in list(await asyncio.to_thread(mt5.positions_get, symbol=sym) or []):
        if p.magic != MAGIC:
            continue
        tick = await asyncio.to_thread(mt5.symbol_info_tick, p.symbol)
        if tick is None:
            continue
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                   "position": p.ticket, "volume": p.volume,
                   "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                   "price": tick.bid if is_buy else tick.ask, "deviation": 30,
                   "magic": MAGIC, "comment": f"Auric kill switch {sym}",
                   "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        result = await asyncio.to_thread(mt5.order_send, request)
        closed += int(bool(result and result.retcode == mt5.TRADE_RETCODE_DONE))
    journal.add(mode="live", side="system", strategy="risk", reason=f"Kill switch activated for {sym}",
                raw={"closed": closed, "cancelled": cancelled})
    await tg_notify(
        f"<b>Auric KILL SWITCH {sym}</b>\n"
        f"Closed: {closed} | Cancelled: {cancelled}\n"
        f"All positions flattened.")
    return {"ok": True, "mode": "live", "symbol": sym, "closed": closed, "cancelled": cancelled, "halted": True}


# --- Kronos forecasting (local candle datasets) -----------------------------
try:
    import kronos_engine  # lazy: imports torch/pandas on first real use

    KRONOS_OK = True
except Exception:  # pragma: no cover - deps optional
    kronos_engine = None
    KRONOS_OK = False


def _local_datasets():
    """Discover local OHLCV datasets shiped with or added to the kronos folder."""
    data_dir = ROOT / "kronos" / "finetune_csv" / "data"
    if not data_dir.exists():
        return []
    out = []
    for p in sorted(data_dir.glob("*.csv")):
        out.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
    return out


@app.get("/api/kronos/status")
async def kronos_status():
    if not KRONOS_OK:
        return {"ok": False, "reason": "torch/pandas not installed", "datasets": _local_datasets()}
    return {"ok": True, "datasets": _local_datasets()}


@app.get("/api/kronos/datasets")
async def kronos_datasets():
    return {"datasets": _local_datasets()}


@app.post("/api/kronos/forecast")
async def kronos_forecast(req: KronosRequest):
    if not KRONOS_OK:
        raise HTTPException(503, "Kronos dependencies (torch/pandas) are not installed")
    datasets = {d["name"]: d["path"] for d in _local_datasets()}
    if req.dataset not in datasets:
        raise HTTPException(422, f"Unknown dataset '{req.dataset}'. Available: {list(datasets)} or []")
    try:
        return await asyncio.to_thread(
            kronos_engine.forecast, datasets[req.dataset],
            lookback=req.lookback, pred_len=req.pred_len, T=req.T,
            top_p=req.top_p, sample_count=req.sample_count, model_id=req.model)
    except Exception as exc:  # pragma: no cover
        logger.exception("Kronos forecast failed")
        raise HTTPException(500, f"Kronos forecast failed: {exc}")


# Serve the built React app (web/dist) as static files for any non-API path.
# Mounted last so /api/* and /ws/* routes take precedence.
if (WEB_DIST / "assets").exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

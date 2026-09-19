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
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from production_core import (
    AuditLog,
    BlackoutGuard,
    ExecutionPolicy,
    OperatorAuth,
    ReconciliationState,
    TokenBucketLimiter,
    production_readiness,
)
from engine import (STRATEGIES, SIZERS, Journal, RiskManager, atr, backtest,
                    indicators, monte_carlo, optimize, position_size, signal)
from execution_v2 import (
    ExecutionLedger,
    PaperBroker,
    choose_filling,
    fallback_spec,
    normalize_price,
    normalize_volume,
    position_size_for_risk,
    risk_per_lot,
    spec_from_info,
    spec_payload,
    spread_points,
)

logger = logging.getLogger("auric")

ROOT = Path(__file__).parent
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
TD_SYMBOL = os.getenv("TWELVE_DATA_SYMBOL", "XAU/USD")
TD_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
SOURCE = os.getenv("MARKET_DATA_SOURCE", "auto").lower()
LIVE_ENABLED = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
# Manual live execution and autonomous live execution are deliberately separate.
AUTO_LIVE_ENABLED = os.getenv("ENABLE_AUTO_LIVE_TRADING", "false").lower() == "true"
ENVIRONMENT = os.getenv("AURIC_ENV", "development").lower()
LIVE_API_KEY = os.getenv("AURIC_LIVE_API_KEY", "")
MAX_LOT = float(os.getenv("MAX_LOT", "1.0"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "500.0"))
MAX_SPREAD_POINTS = float(os.getenv("MAX_SPREAD_POINTS", "80"))
DEFAULT_SPREAD_LIMITS = {"XAUUSD": 80.0, "BTCUSD": 1500.0, "EURUSD": 30.0}

def max_spread_points_for(symbol: str) -> float:
    specific = os.getenv(f"MAX_SPREAD_POINTS_{symbol.upper()}")
    if specific:
        return float(specific)
    generic = os.getenv("MAX_SPREAD_POINTS")
    if generic:
        return float(generic)
    return DEFAULT_SPREAD_LIMITS.get(symbol.upper(), MAX_SPREAD_POINTS)

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
#: Per-symbol tick cache, always a {SYMBOL: tick} map. `latest` above mirrors
#: the primary symbol so single-symbol clients keep working.
latest_by_symbol: dict[str, dict] = {}
feed_task: asyncio.Task | None = None
mt5_ready = False
# Portfolio risk is symbol-agnostic; spread is checked separately against each
# instrument's point-based threshold.
risk = RiskManager(
    daily_loss=MAX_DAILY_LOSS,
    max_lot=MAX_LOT,
    spread_guard=1e12,
)

journal = Journal(str(ROOT / "auric.db"))
execution_ledger = ExecutionLedger(str(ROOT / "auric.db"))
paper_broker = PaperBroker()
execution_policy = ExecutionPolicy()
operator_auth = OperatorAuth()
rate_limiter = TokenBucketLimiter(
    capacity=int(os.getenv("AURIC_RATE_LIMIT_BURST", "120")),
    refill_per_sec=float(os.getenv("AURIC_RATE_LIMIT_PER_SECOND", "2")),
)
audit_log = AuditLog(str(ROOT / "auric.db"))
blackout_guard = BlackoutGuard()
reconciliation = ReconciliationState()
reconciliation_task: asyncio.Task | None = None
METRICS = {
    "requests": 0,
    "errors": 0,
    "orders": 0,
    "live_orders": 0,
    "kills": 0,
    "rate_limited": 0,
    "auth_failures": 0,
}

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

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class OrderRequest(BaseModel):
    side: Literal["buy", "sell"]
    lots: float = Field(gt=0, le=100)
    order_type: Literal["market", "limit", "stop"] = "market"
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    mode: Literal["paper", "live"] = "paper"
    symbol: str = SYMBOL
    client_order_id: str = Field(min_length=8, max_length=80)


class RiskPreviewRequest(BaseModel):
    symbol: str = SYMBOL
    side: Literal["buy", "sell"] = "buy"
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float | None = Field(default=None, gt=0)
    risk_pct: float = Field(default=0.5, gt=0, le=10)
    risk_amount: float | None = Field(default=None, gt=0)

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


def _bearer_token_from_headers(headers) -> str:
    value = headers.get("authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _actor_from_request(request: Request) -> str:
    claims = getattr(request.state, "claims", None)
    return str(claims.get("sub", "anonymous")) if isinstance(claims, dict) else "anonymous"


def _require_live_auth(request: Request) -> None:
    """Fail closed for live mutations unless an explicit API key is configured."""
    if not LIVE_API_KEY:
        raise HTTPException(503, "Live execution requires AURIC_LIVE_API_KEY to be configured")
    supplied = request.headers.get("x-auric-key", "")
    if not supplied or not hmac.compare_digest(supplied, LIVE_API_KEY):
        raise HTTPException(401, "Invalid or missing live execution key")


async def _portfolio_guard(symbol: str, proposed_lots: float, price: float, spec) -> dict:
    """Cross-asset concentration guard measured in notional/equity."""
    if not mt5_ready or not mt5:
        return {"allowed": True, "reason": "Broker portfolio unavailable in paper mode"}
    account_info = await asyncio.to_thread(mt5.account_info)
    if account_info is None or float(account_info.equity) <= 0:
        return {"allowed": False, "reason": "Account equity unavailable"}
    equity = float(account_info.equity)
    max_gross = float(os.getenv("MAX_GROSS_LEVERAGE", "3.0"))
    max_symbol_pct = float(os.getenv("MAX_SYMBOL_NOTIONAL_PCT", "150"))
    rows = list(await asyncio.to_thread(mt5.positions_get) or [])
    gross = 0.0
    symbol_notional = 0.0
    for p in rows:
        if getattr(p, "magic", None) != MAGIC:
            continue
        info = await asyncio.to_thread(mt5.symbol_info, p.symbol)
        pspec = spec_from_info(p.symbol, info) if info else fallback_spec(p.symbol)
        market = float(getattr(p, "price_current", 0.0) or getattr(p, "price_open", 0.0) or 0.0)
        notional = abs(float(p.volume) * pspec.contract_size * market)
        gross += notional
        if p.symbol == symbol:
            symbol_notional += notional
    proposed = abs(float(proposed_lots) * spec.contract_size * float(price))
    if gross + proposed > equity * max_gross:
        return {"allowed": False, "reason": f"Gross exposure cap ({max_gross:.2f}x equity)"}
    if symbol_notional + proposed > equity * (max_symbol_pct / 100.0):
        return {"allowed": False, "reason": f"{symbol} concentration cap ({max_symbol_pct:.0f}% equity)"}
    return {
        "allowed": True,
        "reason": "Portfolio exposure within limits",
        "grossNotional": gross,
        "proposedNotional": proposed,
    }


async def reconciliation_loop():
    """Continuously reconcile recent Auric execution tickets against MT5 state/history."""
    while True:
        try:
            if not mt5_ready or not mt5:
                reconciliation.ok = not (LIVE_ENABLED or AUTO_LIVE_ENABLED)
                reconciliation.broker_connected = False
                reconciliation.error = None if reconciliation.ok else "MT5 unavailable"
                reconciliation.last_sync_ms = int(time.time() * 1000)
            else:
                positions = list(await asyncio.to_thread(mt5.positions_get) or [])
                orders = list(await asyncio.to_thread(mt5.orders_get) or [])
                start = datetime.combine(datetime.now().date(), dtime.min)
                hist_orders = list(await asyncio.to_thread(mt5.history_orders_get, start, datetime.now()) or [])
                deals = list(await asyncio.to_thread(mt5.history_deals_get, start, datetime.now()) or [])
                known: set[str] = set()
                for row in positions + orders + hist_orders:
                    ticket = getattr(row, "ticket", None)
                    if ticket is not None:
                        known.add(str(ticket))
                for deal in deals:
                    for value in (getattr(deal, "ticket", None), getattr(deal, "order", None)):
                        if value is not None:
                            known.add(str(value))
                recent = execution_ledger.recent_live_tickets(250)
                reconciliation.unmatched_tickets = [t for t in recent if t not in known][:25]
                reconciliation.broker_connected = True
                reconciliation.position_count = sum(1 for p in positions if getattr(p, "magic", None) == MAGIC)
                reconciliation.pending_count = sum(1 for p in orders if getattr(p, "magic", None) == MAGIC)
                reconciliation.ok = not reconciliation.unmatched_tickets
                reconciliation.error = None if reconciliation.ok else "Execution tickets missing from broker state/history"
                reconciliation.last_sync_ms = int(time.time() * 1000)
        except Exception as exc:
            reconciliation.ok = False
            reconciliation.error = str(exc)
            reconciliation.last_sync_ms = int(time.time() * 1000)
        await asyncio.sleep(max(5, int(os.getenv("AURIC_RECONCILE_SECONDS", "15"))))


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
    # Paper positions and pending orders are advanced by the same normalized
    # market ticks used by the UI, so paper mode has real lifecycle semantics.
    events = paper_broker.on_tick(
        data.get("symbol", SYMBOL),
        float(data.get("bid", 0) or 0),
        float(data.get("ask", 0) or 0),
    )
    for event in events:
        if event.get("type") == "close":
            journal.add(
                mode="paper",
                symbol=event["symbol"],
                side=event["side"],
                lots=event["lots"],
                entry=event["entry"],
                exit=event["exit"],
                pnl=event["pnl"],
                strategy="manual",
                reason=f"Paper {event.get('reason', 'exit')}",
                raw={"ticket": event["ticket"]},
            )
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
    # Honest deterministic-ish fallback scales per asset instead of pretending
    # every symbol trades like gold.
    demos = {"XAUUSD": 5000.0, "BTCUSD": 97000.0, "EURUSD": 1.0850}
    demo_half_spread = {"XAUUSD": 0.09, "BTCUSD": 4.0, "EURUSD": 0.00005}
    demo_move = {"XAUUSD": 0.45, "BTCUSD": 18.0, "EURUSD": 0.00008}
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
                    demo_price = demos.get(sym, 100.0)
                    delta = demo_move.get(sym, max(demo_price * 0.0001, 0.00001))
                    floor = 0.00001 if demo_price < 10 else 1.0
                    demo_price = max(floor, demo_price + random.uniform(-delta, delta))
                    demos[sym] = demo_price
                    half = demo_half_spread.get(sym, max(demo_price * 0.00002, 0.00001))
                    tick = {"symbol": sym, "bid": demo_price - half, "ask": demo_price + half,
                            "price": demo_price, "spread": half * 2, "source": "Demo",
                            "timestamp": int(time.time() * 1000)}
                overall_latest[sym] = tick
                await broadcast(tick)
            latest_by_symbol.clear()
            latest_by_symbol.update(overall_latest)
            latest = overall_latest.get(SYMBOL, {"symbol": SYMBOL, "source": "none"})
            await asyncio.sleep(0.5)

def engine_snapshot():
    # V2 uses one SymbolEngine implementation for every symbol.  The legacy
    # primary-engine structures remain for backward compatibility only.
    if SYMBOL in ENGINES:
        snap = ENGINES[SYMBOL].snapshot()
        snap["manualLiveEnabled"] = LIVE_ENABLED
        snap["autoLiveEnabled"] = AUTO_LIVE_ENABLED
        return snap
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
                 "dailyLoss": MAX_DAILY_LOSS, "maxSpreadPoints": MAX_SPREAD_POINTS},
        "manualLiveEnabled": LIVE_ENABLED,
        "autoLiveEnabled": AUTO_LIVE_ENABLED,
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
    risk.realized = sum(
        float(getattr(d, "profit", 0.0) or 0.0)
        + float(getattr(d, "commission", 0.0) or 0.0)
        + float(getattr(d, "swap", 0.0) or 0.0)
        + float(getattr(d, "fee", 0.0) or 0.0)
        for d in deals
        if getattr(d, "magic", None) == MAGIC
    )

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
    sym_tick = latest_by_symbol.get(SYMBOL, latest if isinstance(latest, dict) else {})
    decision = risk.check(add, len(open_rows), total_volume, float(sym_tick.get("spread", 0) or 0))
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
    sym_tick = latest_by_symbol.get(SYMBOL, latest if isinstance(latest, dict) else {})
    decision = risk.check(size, len(open_rows), exposure, float(sym_tick.get("spread", 0) or 0))
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

async def _kronos_source_candles() -> list[dict] | None:
    """Best-effort candle source for the Kronos loop: MT5 -> Yahoo -> Demo."""
    need = KRONOS_LOOKBACK + 50
    if mt5_ready and mt5:
        tf = MT5_TIMEFRAMES.get(ENGINE_CONFIG["timeframe"])
        if tf:
            try:
                rates = await asyncio.to_thread(
                    mt5.copy_rates_from_pos, SYMBOL, tf, 0, need)
                if rates is not None and len(rates) >= KRONOS_LOOKBACK + 1:
                    return [
                        {"time": int(r["time"]), "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]),
                         "volume": float(r["tick_volume"])}
                        for r in rates
                    ]
            except Exception as exc:
                logger.warning("Kronos MT5 fetch failed: %s", exc)
    # Yahoo fallback (optional dependency)
    try:
        yf = await asyncio.to_thread(__import__, "yfinance")
    except Exception:
        yf = None
    if yf is not None:
        try:
            yf_interval, yf_period = _YF_INTERVAL_MAP.get(
                ENGINE_CONFIG["timeframe"], ("15m", "60d"))
            ticker_map = {"XAUUSD": "GC=F"}
            df = await asyncio.to_thread(
                lambda: yf.Ticker(ticker_map.get(SYMBOL, SYMBOL)).history(
                    period=yf_period, interval=yf_interval))
            if df is not None and len(df) >= KRONOS_LOOKBACK + 1:
                out = []
                for idx, row in df.tail(need).iterrows():
                    try:
                        ts = int(idx.timestamp())
                    except Exception:
                        continue
                    out.append({"time": ts, "open": float(row["Open"]),
                                "high": float(row["High"]), "low": float(row["Low"]),
                                "close": float(row["Close"]),
                                "volume": float(row.get("Volume", 0) or 0)})
                if len(out) >= KRONOS_LOOKBACK + 1:
                    return out
        except Exception as exc:
            logger.warning("Kronos Yahoo fetch failed: %s", exc)
    # Demo series keeps the AI loop alive offline (honestly labelled).
    try:
        return [{"time": int(c["time"] / 1000), "open": c["open"],
                 "high": c["high"], "low": c["low"], "close": c["close"],
                 "volume": c["volume"]}
                for c in _demo_candles(SYMBOL, ENGINE_CONFIG["timeframe"], need)]
    except Exception:
        return None


async def kronos_forecast_loop():
    """Periodically forecast direction using Kronos on live MT5 candles."""
    global KRONOS_CACHE
    # wait briefly for MT5; proceed with Yahoo/Demo sources when offline
    for _ in range(15):
        if mt5_ready:
            break
        await asyncio.sleep(2)

    while True:
        try:
            if KRONOS_OK:
                candles = await _kronos_source_candles()
                if candles and len(candles) >= KRONOS_LOOKBACK + 1:
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
    global feed_task, engine_task, kronos_task, mt5_ready, reconciliation_task
    await init_mt5()
    feed_task = asyncio.create_task(market_loop())
    reconciliation_task = asyncio.create_task(reconciliation_loop())
    # V2 retires the duplicate legacy primary engine loop.  Every tracked
    # symbol, including XAUUSD, now uses SymbolEngine.
    engine_task = None
    kronos_task = None

    mt5_ref = {"ok": mt5_ready}

    async def _sync_mt5_ref():
        while True:
            mt5_ref["ok"] = bool(mt5_ready)
            await asyncio.sleep(2)

    sync_task = asyncio.create_task(_sync_mt5_ref())
    for sym in ALL_SYMBOLS:
        eng = SymbolEngine(
            symbol=sym,
            mt5_mod=mt5,
            mt5_ready_ref=mt5_ref,
            magic=MAGIC,
            live_enabled=AUTO_LIVE_ENABLED and execution_policy.auto_live_allowed,
            max_lot=MAX_LOT,
            max_daily_loss=MAX_DAILY_LOSS,
            journal=journal,
            tg_notify_fn=tg_notify,
            kronos_engine_mod=kronos_engine,
            kronos_ok=KRONOS_OK,
            mt5_timeframes=MT5_TIMEFRAMES,
            engine_mod=None,
            trade_guard_fn=blackout_guard.check,
            paper_enabled=execution_policy.paper_allowed,
        )
        ENGINES[sym] = eng
        # Start background tasks for every symbol; enable/disable only gates
        # strategy execution and never destroys the task lifecycle.
        eng.start()

    logger.info(
        "Auric V2 engines started: %s | manual_live=%s | auto_live=%s",
        list(ENGINES.keys()), LIVE_ENABLED, AUTO_LIVE_ENABLED,
    )
    yield

    if feed_task:
        feed_task.cancel()
    if reconciliation_task:
        reconciliation_task.cancel()
    sync_task.cancel()
    for eng in ENGINES.values():
        eng.stop()
    if mt5_ready and mt5:
        mt5.shutdown()

app = FastAPI(title="AuricTerminal Gateway", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def production_guard(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or secrets.token_hex(12)
    request.state.request_id = request_id
    remote = request.client.host if request.client else "unknown"
    key = f"{remote}:{request.url.path}"
    cost = 1.0 if request.method not in ("GET", "HEAD", "OPTIONS") else 0.2
    if request.url.path.startswith("/api/") and not rate_limiter.allow(key, cost):
        METRICS["rate_limited"] += 1
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded", "requestId": request_id},
            headers={"Retry-After": "1", "X-Request-ID": request_id},
        )

    public = {"/api/health", "/api/readiness", "/api/auth/login"}
    claims = None
    if operator_auth.require_auth and request.url.path.startswith("/api/") and request.url.path not in public:
        token = _bearer_token_from_headers(request.headers)
        try:
            claims = operator_auth.verify(token)
        except PermissionError as exc:
            METRICS["auth_failures"] += 1
            audit_log.write(
                actor="anonymous", action=request.method, resource=request.url.path,
                outcome="auth_denied", request_id=request_id, remote=remote,
                details={"reason": str(exc)},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": str(exc), "requestId": request_id},
                headers={"X-Request-ID": request_id},
            )
    request.state.claims = claims
    METRICS["requests"] += 1
    response = await call_next(request)
    if response.status_code >= 400:
        METRICS["errors"] += 1
    response.headers["X-Request-ID"] = request_id
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        audit_log.write(
            actor=_actor_from_request(request), action=request.method,
            resource=request.url.path, outcome=str(response.status_code),
            request_id=request_id, remote=remote,
        )
    return response


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

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    try:
        token = operator_auth.issue(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    except PermissionError:
        raise HTTPException(401, "Invalid credentials")
    return {
        "token": token,
        "expiresIn": operator_auth.ttl_seconds,
        "user": req.username,
        "role": "operator",
    }


@app.get("/api/auth/me")
async def auth_me(request: Request):
    claims = getattr(request.state, "claims", None)
    return {"authenticated": bool(claims), "claims": claims}


@app.get("/api/readiness")
async def readiness():
    payload = production_readiness(
        env_name=ENVIRONMENT,
        policy=execution_policy,
        auth=operator_auth,
        live_enabled=LIVE_ENABLED,
        auto_live_enabled=AUTO_LIVE_ENABLED,
        live_api_key=LIVE_API_KEY,
        mt5_connected=bool(mt5_ready),
        reconciliation=reconciliation,
    )
    if not payload["ready"]:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/production/status")
async def production_status():
    return {
        "environment": ENVIRONMENT,
        "policy": execution_policy.payload(),
        "authRequired": operator_auth.require_auth,
        "authConfigured": operator_auth.configured,
        "blackout": {sym: blackout_guard.check(sym) for sym in ALL_SYMBOLS},
        "reconciliation": reconciliation.payload(),
        "limits": {
            "maxLot": MAX_LOT,
            "maxDailyLoss": MAX_DAILY_LOSS,
            "maxGrossLeverage": float(os.getenv("MAX_GROSS_LEVERAGE", "3.0")),
            "maxSymbolNotionalPct": float(os.getenv("MAX_SYMBOL_NOTIONAL_PCT", "150")),
        },
    }


@app.get("/api/audit")
async def audit_events(limit: int = 100):
    return {"events": audit_log.recent(limit)}


@app.get("/api/metrics")
async def metrics():
    lines = [
        "# TYPE auric_requests_total counter",
        f"auric_requests_total {METRICS['requests']}",
        "# TYPE auric_errors_total counter",
        f"auric_errors_total {METRICS['errors']}",
        "# TYPE auric_orders_total counter",
        f"auric_orders_total {METRICS['orders']}",
        "# TYPE auric_live_orders_total counter",
        f"auric_live_orders_total {METRICS['live_orders']}",
        "# TYPE auric_kills_total counter",
        f"auric_kills_total {METRICS['kills']}",
        "# TYPE auric_rate_limited_total counter",
        f"auric_rate_limited_total {METRICS['rate_limited']}",
        "# TYPE auric_auth_failures_total counter",
        f"auric_auth_failures_total {METRICS['auth_failures']}",
        f"auric_reconciliation_ok {1 if reconciliation.ok else 0}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/reconciliation")
async def reconciliation_status():
    return reconciliation.payload()


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "source": latest.get("source"),
        "liveTrading": LIVE_ENABLED,
        "autoLiveTrading": AUTO_LIVE_ENABLED,
        "environment": ENVIRONMENT,
        "executionStage": execution_policy.stage,
        "authRequired": operator_auth.require_auth,
        "ready": production_readiness(
            env_name=ENVIRONMENT, policy=execution_policy, auth=operator_auth,
            live_enabled=LIVE_ENABLED, auto_live_enabled=AUTO_LIVE_ENABLED,
            live_api_key=LIVE_API_KEY, mt5_connected=bool(mt5_ready),
            reconciliation=reconciliation,
        )["ready"],
        "symbol": SYMBOL,
        "timestamp": int(time.time() * 1000),
    }

@app.get("/api/quote")
async def quote():
    if isinstance(latest, dict) and latest.get("symbol"):
        return latest
    if SYMBOL in latest_by_symbol:
        return latest_by_symbol[SYMBOL]
    return {"symbol": SYMBOL, "bid": 0.0, "ask": 0.0, "price": 0.0,
            "spread": 0.0, "source": "connecting",
            "timestamp": int(time.time() * 1000)}

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

    cache = latest_by_symbol.get(sym)
    if isinstance(cache, dict) and cache.get("source"):
        # Live broadcast cache is fresh (<5s old) — prefer it over Yahoo.
        try:
            age_ms = int(time.time() * 1000) - int(cache.get("timestamp", 0))
        except Exception:
            age_ms = 10 ** 9
        if cache.get("source") == "MT5" or age_ms < 5000:
            return cache

    # Yahoo Finance fallback for real-time quote (optional dependency)
    YAHOO_TICKERS = {
        "XAUUSD": "GC=F", "BTCUSD": "BTC-USD",
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X", "EURJPY": "EURJPY=X",
        "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
        "USDCHF": "USDCHF=X", "NZDUSD": "NZDUSD=X",
    }
    yahoo_sym = YAHOO_TICKERS.get(sym, SYMBOL_PROPS.get(sym, {}).get("td_symbol", sym))
    try:
        yf = await asyncio.to_thread(__import__, "yfinance")
    except Exception:
        yf = None
    if yf is not None:
        try:
            ticker = yf.Ticker(yahoo_sym)
            info = await asyncio.to_thread(lambda: ticker.info)
            price = float(info.get("regularMarketPrice", 0) or info.get("previousClose", 0) or 0)
            if price <= 0:
                hist = await asyncio.to_thread(lambda: ticker.history(period="1d"))
                if hist is not None and not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price > 0:
                spread_est = price * 0.0001 if "XAUUSD" not in sym and "BTC" not in sym else 0.50
                return {
                    "symbol": sym, "bid": price - spread_est, "ask": price + spread_est,
                    "price": price, "spread": spread_est * 2, "source": "Yahoo",
                    "timestamp": int(time.time() * 1000),
                }
        except Exception as exc:
            logger.warning("Yahoo quote failed for %s: %s", sym, exc)

    if isinstance(cache, dict) and cache.get("source"):
        return cache

    # Last resort: stable fallback
    seed = 4000.0 if sym == "XAUUSD" else (70000.0 if sym == "BTCUSD" else 1.0)
    base = 1.08 if sym == "EURUSD" else (1.27 if sym == "GBPUSD" else (149.0 if sym == "USDJPY" else seed))
    price = float(base)
    return {
        "symbol": sym, "bid": price - 0.05, "ask": price + 0.05, "price": price,
        "spread": 0.10, "source": "Fallback", "timestamp": int(time.time() * 1000),
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
async def symbol_start(symbol: str, request: Request):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    if AUTO_LIVE_ENABLED and execution_policy.auto_live_allowed:
        _require_live_auth(request)
    ENGINES[sym].enable()
    return ENGINES[sym].snapshot()


@app.post("/api/symbols/{symbol}/stop")
async def symbol_stop(symbol: str):
    sym = symbol.upper()
    if sym not in ENGINES:
        raise HTTPException(404, f"Symbol {sym} not tracked")
    ENGINES[sym].disable()
    return ENGINES[sym].snapshot()


@app.get("/api/symbols/all/kronos")
async def all_kronos():
    return {"symbols": {sym: ENGINES[sym].kronos_cache for sym in ALL_SYMBOLS if sym in ENGINES}}


@app.post("/api/engine/start")
async def engine_start(request: Request):
    if AUTO_LIVE_ENABLED and execution_policy.auto_live_allowed:
        _require_live_auth(request)
    if SYMBOL not in ENGINES:
        raise HTTPException(503, "Primary engine is not initialized")
    ENGINES[SYMBOL].enable()
    return engine_snapshot()


@app.post("/api/engine/stop")
async def engine_stop():
    if SYMBOL in ENGINES:
        ENGINES[SYMBOL].disable()
    return engine_snapshot()


@app.post("/api/engine/reset")
async def engine_reset():
    risk.halted = False
    for eng in ENGINES.values():
        eng.reset_risk()
    return engine_snapshot()


@app.get("/api/account")
async def account():
    if not mt5_ready or not mt5:
        src = latest.get("source") if isinstance(latest, dict) else "Demo"
        return {"connected": False, "source": src}
    info = await asyncio.to_thread(mt5.account_info)
    if not info:
        raise HTTPException(503, "MT5 account information unavailable")
    return {"connected": True, "login": info.login, "balance": info.balance,
            "equity": info.equity, "margin": info.margin, "freeMargin": info.margin_free,
            "marginLevel": info.margin_level, "currency": info.currency}

@app.get("/api/positions")
async def positions(
    symbol: str | None = None,
    mode: Literal["paper", "live", "all"] = "all",
):
    sym = symbol.upper() if symbol else None
    out: list[dict] = []
    if mode in ("paper", "all"):
        out.extend(paper_broker.positions(sym))
    if mode in ("live", "all") and mt5_ready and mt5:
        rows = await asyncio.to_thread(mt5.positions_get) or []
        ours = [p for p in rows if p.magic == MAGIC and (sym is None or p.symbol == sym)]
        out.extend([{
            "ticket": p.ticket, "symbol": p.symbol,
            "side": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
            "lots": p.volume, "entry": p.price_open, "market": p.price_current,
            "sl": p.sl, "tp": p.tp, "pnl": p.profit, "mode": "live",
        } for p in ours])
    payload = {"positions": out}
    if sym:
        payload["symbol"] = sym
    return payload


@app.get("/api/pending")
async def pending_orders(symbol: str | None = None, mode: Literal["paper", "live", "all"] = "all"):
    sym = symbol.upper() if symbol else None
    out = []
    if mode in ("paper", "all"):
        out.extend(paper_broker.pending(sym))
    if mode in ("live", "all") and mt5_ready and mt5:
        rows = await asyncio.to_thread(mt5.orders_get) or []
        for p in rows:
            if getattr(p, "magic", None) != MAGIC or (sym and p.symbol != sym):
                continue
            out.append({
                "ticket": p.ticket, "symbol": p.symbol, "lots": p.volume_current,
                "entry": p.price_open, "sl": p.sl, "tp": p.tp, "mode": "live",
            })
    return {"orders": out}


@app.post("/api/risk/reset")
async def reset_risk():
    risk.halted = False
    for eng in ENGINES.values():
        eng.reset_risk()
    return {"ok": True, "halted": False}


@app.post("/api/risk/preview")
async def risk_preview(req: RiskPreviewRequest):
    sym = req.symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    info = await asyncio.to_thread(mt5.symbol_info, sym) if mt5_ready and mt5 else None
    spec = spec_from_info(sym, info) if info else fallback_spec(sym)
    account_info = await asyncio.to_thread(mt5.account_info) if mt5_ready and mt5 else None
    equity = float(account_info.equity) if account_info else 10000.0
    effective_pct = req.risk_pct
    if req.risk_amount is not None:
        effective_pct = min(10.0, req.risk_amount / max(equity, 1e-9) * 100.0)
    lots = position_size_for_risk(equity, effective_pct, req.entry, req.stop, spec, MAX_LOT)
    risk_usd = risk_per_lot(req.entry, req.stop, spec) * lots
    reward_usd = None
    rr = None
    if req.target is not None:
        reward_per_lot = risk_per_lot(req.entry, req.target, spec)
        reward_usd = reward_per_lot * lots
        rr = reward_usd / risk_usd if risk_usd > 0 else None
    margin = None
    if mt5_ready and mt5:
        typ = mt5.ORDER_TYPE_BUY if req.side == "buy" else mt5.ORDER_TYPE_SELL
        try:
            margin = await asyncio.to_thread(mt5.order_calc_margin, typ, sym, lots, req.entry)
        except Exception:
            margin = None
    return {
        "symbol": sym,
        "equity": equity,
        "lots": lots,
        "riskUsd": round(risk_usd, 2),
        "rewardUsd": round(reward_usd, 2) if reward_usd is not None else None,
        "rr": round(rr, 2) if rr is not None else None,
        "margin": round(float(margin), 2) if margin is not None else None,
        "spec": spec_payload(spec),
    }


#: Canonical interval -> Yahoo Finance interval + suitable history period.
_YF_INTERVAL_MAP = {
    "M1": ("1m", "7d"), "1min": ("1m", "7d"),
    "M5": ("5m", "60d"), "5min": ("5m", "60d"),
    "M15": ("15m", "60d"), "15min": ("15m", "60d"),
    "M30": ("30m", "60d"), "30min": ("30m", "60d"),
    "H1": ("1h", "730d"), "1h": ("1h", "730d"),
    "H4": ("1h", "730d"), "4h": ("1h", "730d"),
    "D1": ("1d", "5y"), "1day": ("1d", "5y"),
    "W1": ("1wk", "max"), "1week": ("1wk", "max"),
}

_INTERVAL_SECONDS = {
    "M1": 60, "1min": 60, "M5": 300, "5min": 300,
    "M15": 900, "15min": 900, "M30": 1800, "30min": 1800,
    "H1": 3600, "1h": 3600, "H4": 14400, "4h": 14400,
    "D1": 86400, "1day": 86400, "W1": 604800, "1week": 604800,
}

_DEMO_BASE_PRICE = {
    "XAUUSD": 5000.0, "BTCUSD": 97000.0, "EURUSD": 1.0850,
    "GBPUSD": 1.2700, "USDJPY": 149.50, "USDCHF": 0.8900,
    "AUDUSD": 0.6600, "NZDUSD": 0.6000, "USDCAD": 1.3600,
}


def _demo_candles(symbol: str, interval: str, outputsize: int) -> list[dict]:
    """Deterministic synthetic candles so the terminal always renders.

    Seeded per symbol+interval for stability across reloads; always
    labelled ``source="Demo"`` so it is never mistaken for market data.
    """
    import math as _math
    step = _INTERVAL_SECONDS.get(interval, 900)
    base = _DEMO_BASE_PRICE.get(symbol, 100.0)
    seed = abs(hash((symbol, interval))) % (2 ** 32)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - outputsize * step * 1000
    out: list[dict] = []
    price = base
    for i in range(outputsize):
        seed = (seed * 1664525 + 1013904223) % 4294967296
        r = seed / 4294967296 - 0.47
        o = price
        c = o + r * base * 0.0012 + _math.sin(i / 17) * base * 0.0002
        h = max(o, c) + base * 0.0004 + (i % 7) * base * 0.00003
        lo = min(o, c) - base * 0.0004 - (i % 5) * base * 0.00003
        out.append({"time": start_ms + i * step * 1000, "open": round(o, 5),
                    "high": round(h, 5), "low": round(lo, 5),
                    "close": round(c, 5), "volume": float(100 + (i % 31) * 8)})
        price = c
    return out


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
    # Yahoo Finance fallback when MT5 not available (optional dependency).
    YAHOO_MAP = {
        "XAUUSD": "GC=F",
        "BTCUSD": "BTC-USD",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "EURJPY": "EURJPY=X",
        "AUDUSD": "AUDUSD=X",
        "USDCAD": "USDCAD=X",
        "USDCHF": "USDCHF=X",
        "NZDUSD": "NZDUSD=X",
    }
    yahoo_ticker = YAHOO_MAP.get(sym, SYMBOL_PROPS.get(sym, {}).get("td_symbol", sym))
    yf_interval, yf_period = _YF_INTERVAL_MAP.get(interval, ("1d", "5y"))
    try:
        yf = await asyncio.to_thread(__import__, "yfinance")
    except Exception:
        yf = None
    if yf is not None:
        try:
            df = await asyncio.to_thread(
                lambda: yf.Ticker(yahoo_ticker).history(period=yf_period, interval=yf_interval))
            if df is not None and not df.empty:
                if interval in ("H4", "4h"):
                    # aggregate 1h bars into 4h blocks
                    rows = []
                    buf = []
                    for idx, row in df.iterrows():
                        buf.append((idx, row))
                        if len(buf) == 4:
                            o = float(buf[0][1]["Open"])
                            h = max(float(r[1]["High"]) for r in buf)
                            lo = min(float(r[1]["Low"]) for r in buf)
                            c = float(buf[-1][1]["Close"])
                            v = float(sum(float(r[1].get("Volume", 0) or 0) for r in buf))
                            rows.append((buf[-1][0], o, h, lo, c, v))
                            buf = []
                    values = [{"time": int(ts.timestamp() * 1000), "open": o,
                               "high": h, "low": lo, "close": c, "volume": v}
                              for ts, o, h, lo, c, v in rows[-outputsize:]]
                else:
                    values = []
                    for idx, row in df.tail(outputsize).iterrows():
                        try:
                            ts = int(idx.timestamp() * 1000)
                        except Exception:
                            continue
                        values.append({
                            "time": ts,
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "volume": float(row.get("Volume", 0) or 0),
                        })
                if values:
                    return {"symbol": sym, "interval": interval, "source": "Yahoo", "values": values}
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Yahoo candles failed for %s: %s", sym, exc)
    # Last resort: deterministic demo series so the chart always renders.
    return {"symbol": sym, "interval": interval, "source": "Demo",
            "values": _demo_candles(sym, interval, outputsize)}

@app.get("/api/brain/setup")
async def brain_setup(symbol: str = SYMBOL, interval: str = "M15", lookback: int = 200):
    sym = symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    # Fetch candles via existing logic - reuse candles endpoint logic simplified
    # For now fetch via Yahoo directly
    import brain_agent
    # Get recent candles
    candles_data = await candles(symbol=sym, interval=interval, outputsize=lookback)
    values = candles_data.get("values", [])
    analysis = brain_agent.analyze_symbol(values, sym)
    return analysis

@app.websocket("/ws/market")
async def ws_market(ws: WebSocket):
    if operator_auth.require_auth:
        token = ws.query_params.get("token", "")
        try:
            operator_auth.verify(token)
        except PermissionError:
            await ws.close(code=4401)
            return
    await ws.accept()
    clients.add(ws)
    primary = latest_by_symbol.get(SYMBOL)
    if isinstance(primary, dict) and primary.get("symbol"):
        await ws.send_json({"type": "tick", **primary})
    elif isinstance(latest, dict) and latest.get("symbol"):
        await ws.send_json({"type": "tick", **latest})
    else:
        await ws.send_json({"type": "tick", "symbol": SYMBOL, "bid": 0.0,
                            "ask": 0.0, "price": 0.0, "spread": 0.0,
                            "source": "connecting",
                            "timestamp": int(time.time() * 1000)})
    try:
        while True:
            await ws.receive_text()  # client heartbeat
    except WebSocketDisconnect:
        clients.discard(ws)

@app.post("/api/orders")
async def order(req: OrderRequest, request: Request):
    METRICS["orders"] += 1
    if req.mode == "live":
        METRICS["live_orders"] += 1
    sym = req.symbol.upper()
    if sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    if req.order_type != "market" and req.entry_price is None:
        raise HTTPException(422, "Limit/stop orders require entry_price")
    if req.lots > MAX_LOT:
        raise HTTPException(422, f"Lot size exceeds server hard cap ({MAX_LOT})")

    tick_info = latest_by_symbol.get(sym, {})
    if not tick_info and isinstance(latest, dict):
        if latest.get("symbol") == sym:
            tick_info = latest
        elif isinstance(latest.get(sym), dict):
            tick_info = latest[sym]
    bid = float(tick_info.get("bid", 0) or 0)
    ask = float(tick_info.get("ask", 0) or 0)
    if bid <= 0 or ask <= 0:
        raise HTTPException(503, "No market price available yet")

    info = await asyncio.to_thread(mt5.symbol_info, sym) if mt5_ready and mt5 else None
    spec = spec_from_info(sym, info) if info else fallback_spec(sym)
    lots = normalize_volume(req.lots, spec, MAX_LOT)
    sp_points = spread_points(bid, ask, spec)
    spread_limit = max_spread_points_for(sym)
    if sp_points > spread_limit:
        raise HTTPException(
            403,
            f"Spread guard active ({sp_points:.1f} pts > {spread_limit:.1f} pts for {sym})",
        )
    if req.mode == "paper":
        if not execution_policy.paper_allowed:
            raise HTTPException(403, f"Execution stage '{execution_policy.stage}' does not allow paper orders")
        positions_count = len(paper_broker.positions(sym))
        exposure = sum(float(p["lots"]) for p in paper_broker.positions(sym))
    else:
        open_rows = list(await asyncio.to_thread(mt5.positions_get, symbol=sym) or []) if mt5_ready and mt5 else []
        positions_count = len(open_rows)
        exposure = sum(float(p.volume) for p in open_rows)
    if req.mode == "live":
        if not execution_policy.live_manual_allowed:
            raise HTTPException(403, f"Execution stage '{execution_policy.stage}' does not allow manual live orders")
        blackout = blackout_guard.check(sym)
        if not blackout["allowed"]:
            raise HTTPException(403, blackout["reason"])
        await update_realized()
        if risk.realized <= -MAX_DAILY_LOSS:
            risk.kill()
    decision = risk.check(lots, positions_count, exposure, 0.0)
    if not decision["allowed"]:
        raise HTTPException(403, "; ".join(decision["reasons"]))
    if req.mode == "live":
        exposure_check = await _portfolio_guard(sym, lots, ask if req.side == "buy" else bid, spec)
        if not exposure_check["allowed"]:
            raise HTTPException(403, exposure_check["reason"])

    payload = req.model_dump()
    if not execution_ledger.reserve(req.client_order_id, sym, req.mode, req.order_type, payload):
        existing = execution_ledger.lookup(req.client_order_id)
        raise HTTPException(409, f"Duplicate client_order_id ({existing.get('status') if existing else 'known'})")

    try:
        if req.mode == "paper":
            result = paper_broker.place(
                symbol=sym,
                side=req.side,
                lots=lots,
                order_type=req.order_type,
                bid=bid,
                ask=ask,
                entry_price=req.entry_price,
                stop_loss=req.stop_loss,
                take_profit=req.take_profit,
                client_order_id=req.client_order_id,
                spec=spec,
            )
            journal.add(
                mode="paper", symbol=sym, side=req.side, lots=lots,
                entry=result.get("fillPrice") or req.entry_price,
                strategy="manual",
                reason=f"Paper {req.order_type} order",
                raw=payload,
            )
            response = {
                **result,
                "mode": "paper",
                "symbol": sym,
                "clientOrderId": req.client_order_id,
                "source": tick_info.get("source", "Demo"),
            }
            execution_ledger.complete(req.client_order_id, response, result.get("ticket"))
            return response

        if not LIVE_ENABLED:
            raise HTTPException(403, "Manual live execution is disabled on the server")
        _require_live_auth(request)
        if not mt5_ready or not mt5:
            raise HTTPException(503, "MT5 terminal is not connected")

        tick = await asyncio.to_thread(mt5.symbol_info_tick, sym)
        info = await asyncio.to_thread(mt5.symbol_info, sym)
        if tick is None or info is None:
            raise HTTPException(503, "MT5 symbol/tick unavailable")
        spec = spec_from_info(sym, info)
        lots = normalize_volume(lots, spec, MAX_LOT)
        is_buy = req.side == "buy"
        pending = req.order_type != "market"
        if req.order_type == "market":
            action = mt5.TRADE_ACTION_DEAL
            typ = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            price = normalize_price(tick.ask if is_buy else tick.bid, spec)
        else:
            action = mt5.TRADE_ACTION_PENDING
            if req.order_type == "limit":
                typ = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
            else:
                typ = mt5.ORDER_TYPE_BUY_STOP if is_buy else mt5.ORDER_TYPE_SELL_STOP
            price = normalize_price(float(req.entry_price), spec)

        mt5_request = {
            "action": action,
            "symbol": sym,
            "volume": lots,
            "type": typ,
            "price": price,
            "sl": normalize_price(req.stop_loss, spec) if req.stop_loss else 0.0,
            "tp": normalize_price(req.take_profit, spec) if req.take_profit else 0.0,
            "deviation": 20,
            "magic": MAGIC,
            "comment": f"AuricV2 {req.client_order_id[:16]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": choose_filling(mt5, spec, pending=pending),
        }
        check = await asyncio.to_thread(mt5.order_check, mt5_request)
        valid_codes = {0, getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_PLACED", 10008)}
        if check is not None and getattr(check, "retcode", 0) not in valid_codes:
            raise HTTPException(422, f"MT5 preflight rejected order: {getattr(check, 'comment', 'unknown')}")
        result = await asyncio.to_thread(mt5.order_send, mt5_request)
        accepted_codes = {getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_PLACED", 10008)}
        if result is None or result.retcode not in accepted_codes:
            raise HTTPException(502, f"MT5 rejected order: {getattr(result, 'comment', 'unknown error')}")

        response = {
            "accepted": True,
            "status": "pending" if pending else "filled",
            "mode": "live",
            "symbol": sym,
            "ticket": result.order,
            "deal": getattr(result, "deal", None),
            "fillPrice": getattr(result, "price", None) if not pending else None,
            "entryPrice": price,
            "clientOrderId": req.client_order_id,
        }
        journal.add(
            mode="live", symbol=sym, side=req.side, lots=lots,
            entry=getattr(result, "price", None) or price,
            strategy="manual", reason=f"MT5 {req.order_type} order", raw=payload,
        )
        execution_ledger.complete(req.client_order_id, response, result.order)
        return response
    except HTTPException as exc:
        execution_ledger.fail(req.client_order_id, str(exc.detail))
        raise
    except Exception as exc:
        execution_ledger.fail(req.client_order_id, str(exc))
        raise


@app.post("/api/kill")
async def kill_all(
    request: Request,
    symbol: str = "ALL",
    mode: Literal["paper", "live"] = "paper",
):
    METRICS["kills"] += 1
    sym = symbol.upper()
    if sym != "ALL" and sym not in ALL_SYMBOLS:
        raise HTTPException(422, f"Symbol {sym} not tracked")
    target = None if sym == "ALL" else sym

    risk.kill()
    for eng in ENGINES.values():
        eng.risk.kill()

    if mode == "paper":
        closed, cancelled = paper_broker.flatten(target)
        journal.add(
            mode="paper", side="system", strategy="risk",
            reason=f"GLOBAL kill switch activated for {sym}",
            raw={"closed": closed, "cancelled": cancelled},
        )
        return {
            "ok": True, "mode": "paper", "symbol": sym,
            "closed": closed, "cancelled": cancelled, "halted": True,
        }

    if not LIVE_ENABLED:
        raise HTTPException(403, "Live execution is disabled on the server")
    _require_live_auth(request)
    if not mt5_ready or not mt5:
        raise HTTPException(503, "MT5 terminal is not connected")

    closed = cancelled = 0
    pending_rows = list(await asyncio.to_thread(mt5.orders_get) or [])
    for pending in pending_rows:
        if getattr(pending, "magic", None) != MAGIC or (target and pending.symbol != target):
            continue
        result = await asyncio.to_thread(
            mt5.order_send,
            {"action": mt5.TRADE_ACTION_REMOVE, "order": pending.ticket},
        )
        cancelled += int(bool(result and result.retcode == mt5.TRADE_RETCODE_DONE))

    position_rows = list(await asyncio.to_thread(mt5.positions_get) or [])
    for p in position_rows:
        if p.magic != MAGIC or (target and p.symbol != target):
            continue
        tick = await asyncio.to_thread(mt5.symbol_info_tick, p.symbol)
        info = await asyncio.to_thread(mt5.symbol_info, p.symbol)
        if tick is None or info is None:
            continue
        spec = spec_from_info(p.symbol, info)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "position": p.ticket,
            "volume": normalize_volume(p.volume, spec),
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": normalize_price(tick.bid if is_buy else tick.ask, spec),
            "deviation": 30,
            "magic": MAGIC,
            "comment": "AuricV2 GLOBAL KILL",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": choose_filling(mt5, spec),
        }
        result = await asyncio.to_thread(mt5.order_send, close_request)
        closed += int(bool(result and result.retcode == mt5.TRADE_RETCODE_DONE))

    journal.add(
        mode="live", side="system", strategy="risk",
        reason=f"GLOBAL kill switch activated for {sym}",
        raw={"closed": closed, "cancelled": cancelled},
    )
    await tg_notify(
        f"<b>Auric V2 GLOBAL KILL {sym}</b>\n"
        f"Closed: {closed} | Cancelled: {cancelled}\n"
        "All Auric positions/orders targeted by the kill command were processed."
    )
    return {
        "ok": True, "mode": "live", "symbol": sym,
        "closed": closed, "cancelled": cancelled, "halted": True,
    }


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

"""Auric Terminal V2 execution primitives.

This module keeps broker-specific math, durable order idempotency and paper
execution semantics out of the API/UI layers.  It intentionally contains no
strategy logic: every strategy/manual action produces an order intent and the
execution layer decides how that intent is normalized and filled.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int = 0
    filling_mode: int | None = None


_FALLBACKS: dict[str, SymbolSpec] = {
    "XAUUSD": SymbolSpec("XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 100.0, 0.01),
    "BTCUSD": SymbolSpec("BTCUSD", 2, 0.01, 0.01, 0.01, 1.0, 0.01, 100.0, 0.01),
    "EURUSD": SymbolSpec("EURUSD", 5, 0.00001, 0.00001, 1.0, 100000.0, 0.01, 100.0, 0.01),
}


def fallback_spec(symbol: str) -> SymbolSpec:
    sym = symbol.upper()
    return _FALLBACKS.get(sym, SymbolSpec(sym, 5, 0.00001, 0.00001, 1.0, 1.0, 0.01, 100.0, 0.01))


def spec_from_info(symbol: str, info: Any | None) -> SymbolSpec:
    base = fallback_spec(symbol)
    if info is None:
        return base

    def pos(name: str, default: float) -> float:
        try:
            value = float(getattr(info, name, default) or default)
            return value if value > 0 else default
        except (TypeError, ValueError):
            return default

    digits = int(getattr(info, "digits", base.digits) or base.digits)
    point = pos("point", base.point)
    tick_size = pos("trade_tick_size", point)
    tick_value = pos("trade_tick_value_loss", pos("trade_tick_value", base.tick_value))
    contract_size = pos("trade_contract_size", base.contract_size)
    volume_min = pos("volume_min", base.volume_min)
    volume_max = pos("volume_max", base.volume_max)
    volume_step = pos("volume_step", base.volume_step)
    stops = int(getattr(info, "trade_stops_level", 0) or 0)
    filling = getattr(info, "filling_mode", None)
    return SymbolSpec(
        symbol=symbol.upper(),
        digits=digits,
        point=point,
        tick_size=tick_size,
        tick_value=tick_value,
        contract_size=contract_size,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
        stops_level_points=stops,
        filling_mode=int(filling) if filling is not None else None,
    )


def normalize_price(value: float, spec: SymbolSpec) -> float:
    step = spec.tick_size or spec.point
    if step <= 0:
        return round(float(value), spec.digits)
    units = round(float(value) / step)
    return round(units * step, spec.digits)


def normalize_volume(value: float, spec: SymbolSpec, hard_max: float | None = None) -> float:
    ceiling = min(spec.volume_max, hard_max) if hard_max is not None else spec.volume_max
    raw = max(spec.volume_min, min(float(value), ceiling))
    step = max(spec.volume_step, 1e-9)
    steps = math.floor((raw + 1e-12) / step)
    normalized = steps * step
    decimals = max(0, min(8, int(round(-math.log10(step))) if step < 1 else 0))
    return round(max(spec.volume_min, min(normalized, ceiling)), decimals)


def spread_points(bid: float, ask: float, spec: SymbolSpec) -> float:
    return abs(float(ask) - float(bid)) / max(spec.point, 1e-12)


def risk_per_lot(entry: float, stop: float, spec: SymbolSpec) -> float:
    distance = abs(float(entry) - float(stop))
    if distance <= 0:
        return 0.0
    if spec.tick_size > 0 and spec.tick_value > 0:
        return distance / spec.tick_size * spec.tick_value
    return distance * spec.contract_size


def position_size_for_risk(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    spec: SymbolSpec,
    hard_max: float | None = None,
) -> float:
    risk_budget = max(0.0, float(equity) * max(0.0, float(risk_pct)) / 100.0)
    per_lot = risk_per_lot(entry, stop, spec)
    if risk_budget <= 0 or per_lot <= 0:
        return spec.volume_min
    return normalize_volume(risk_budget / per_lot, spec, hard_max)


def minimum_stop_distance(spec: SymbolSpec) -> float:
    broker_min = spec.stops_level_points * spec.point
    return max(broker_min, spec.tick_size, spec.point)


def choose_filling(mt5_mod: Any, spec: SymbolSpec, pending: bool = False) -> int:
    if pending and hasattr(mt5_mod, "ORDER_FILLING_RETURN"):
        return mt5_mod.ORDER_FILLING_RETURN
    supported = {
        getattr(mt5_mod, "ORDER_FILLING_FOK", -999),
        getattr(mt5_mod, "ORDER_FILLING_IOC", -998),
        getattr(mt5_mod, "ORDER_FILLING_RETURN", -997),
    }
    if spec.filling_mode in supported:
        return int(spec.filling_mode)
    return getattr(mt5_mod, "ORDER_FILLING_IOC", 1)


class ExecutionLedger:
    """Durable client_order_id reservation and execution result ledger."""

    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = Lock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS execution_ledger("
            "client_order_id TEXT PRIMARY KEY, ts INTEGER NOT NULL, symbol TEXT NOT NULL, "
            "mode TEXT NOT NULL, order_type TEXT NOT NULL, status TEXT NOT NULL, "
            "broker_ticket TEXT, payload TEXT NOT NULL, result TEXT)"
        )
        self.db.commit()

    def reserve(self, client_order_id: str, symbol: str, mode: str, order_type: str, payload: dict) -> bool:
        with self._lock:
            try:
                self.db.execute(
                    "INSERT INTO execution_ledger(client_order_id,ts,symbol,mode,order_type,status,payload) "
                    "VALUES(?,?,?,?,?,'reserved',?)",
                    (client_order_id, int(time.time() * 1000), symbol, mode, order_type, json.dumps(payload, default=str)),
                )
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def complete(self, client_order_id: str, result: dict, broker_ticket: Any = None) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE execution_ledger SET status='filled', broker_ticket=?, result=? WHERE client_order_id=?",
                (str(broker_ticket) if broker_ticket is not None else None, json.dumps(result, default=str), client_order_id),
            )
            self.db.commit()

    def fail(self, client_order_id: str, reason: str) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE execution_ledger SET status='rejected', result=? WHERE client_order_id=?",
                (json.dumps({"error": reason}), client_order_id),
            )
            self.db.commit()

    def lookup(self, client_order_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM execution_ledger WHERE client_order_id=?", (client_order_id,)
        ).fetchone()
        return dict(row) if row else None

    def recent(self, limit: int = 500, mode: str | None = None) -> list[dict]:
        if mode:
            rows = self.db.execute(
                "SELECT * FROM execution_ledger WHERE mode=? ORDER BY ts DESC LIMIT ?",
                (mode, max(1, min(limit, 5000))),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM execution_ledger ORDER BY ts DESC LIMIT ?",
                (max(1, min(limit, 5000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def broker_tickets(self, mode: str = "live", limit: int = 5000) -> set[int]:
        rows = self.db.execute(
            "SELECT broker_ticket FROM execution_ledger "
            "WHERE mode=? AND broker_ticket IS NOT NULL ORDER BY ts DESC LIMIT ?",
            (mode, max(1, min(limit, 10000))),
        ).fetchall()
        out: set[int] = set()
        for row in rows:
            try:
                out.add(int(row["broker_ticket"]))
            except (TypeError, ValueError):
                continue
        return out


class PaperBroker:
    """Deterministic paper broker with optional durable SQLite state."""

    def __init__(self, path: str | None = None):
        self._positions: dict[int, dict] = {}
        self._pending: dict[int, dict] = {}
        self._seq = int(time.time() * 1000) % 2_000_000_000
        self._db: sqlite3.Connection | None = None
        if path:
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS paper_state("
                "kind TEXT NOT NULL, ticket INTEGER NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY(kind,ticket))"
            )
            self._db.commit()
            self._restore()

    def _restore(self) -> None:
        if self._db is None:
            return
        rows = self._db.execute("SELECT kind,ticket,payload FROM paper_state").fetchall()
        max_ticket = self._seq
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                ticket = int(row["ticket"])
            except Exception:
                continue
            max_ticket = max(max_ticket, ticket)
            if row["kind"] == "position":
                self._positions[ticket] = payload
            elif row["kind"] == "pending":
                self._pending[ticket] = payload
        self._seq = max_ticket

    def _persist(self) -> None:
        if self._db is None:
            return
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute("DELETE FROM paper_state")
            self._db.executemany(
                "INSERT INTO paper_state(kind,ticket,payload) VALUES('position',?,?)",
                [(ticket, json.dumps(payload, default=str)) for ticket, payload in self._positions.items()],
            )
            self._db.executemany(
                "INSERT INTO paper_state(kind,ticket,payload) VALUES('pending',?,?)",
                [(ticket, json.dumps(payload, default=str)) for ticket, payload in self._pending.items()],
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def _ticket(self) -> int:
        self._seq += 1
        return self._seq

    @staticmethod
    def _side_sign(side: str) -> int:
        return 1 if side == "buy" else -1

    def place(
        self,
        *,
        symbol: str,
        side: str,
        lots: float,
        order_type: str,
        bid: float,
        ask: float,
        entry_price: float | None,
        stop_loss: float | None,
        take_profit: float | None,
        client_order_id: str,
        spec: SymbolSpec,
    ) -> dict:
        ticket = self._ticket()
        lots = normalize_volume(lots, spec)
        if order_type == "market":
            fill = ask if side == "buy" else bid
            pos = {
                "ticket": ticket, "symbol": symbol, "side": side, "lots": lots,
                "entry": normalize_price(fill, spec), "market": normalize_price(fill, spec),
                "sl": normalize_price(stop_loss, spec) if stop_loss else 0.0,
                "tp": normalize_price(take_profit, spec) if take_profit else 0.0,
                "pnl": 0.0, "mode": "paper", "clientOrderId": client_order_id,
                "contractSize": spec.contract_size,
            }
            self._positions[ticket] = pos
            self._persist()
            return {"accepted": True, "status": "filled", "ticket": ticket, "fillPrice": pos["entry"]}

        if not entry_price or entry_price <= 0:
            raise ValueError("Pending orders require a positive entry price")
        order = {
            "ticket": ticket, "symbol": symbol, "side": side, "lots": lots,
            "orderType": order_type, "entry": normalize_price(entry_price, spec),
            "sl": normalize_price(stop_loss, spec) if stop_loss else 0.0,
            "tp": normalize_price(take_profit, spec) if take_profit else 0.0,
            "mode": "paper", "clientOrderId": client_order_id,
            "contractSize": spec.contract_size,
        }
        self._pending[ticket] = order
        self._persist()
        return {"accepted": True, "status": "pending", "ticket": ticket, "fillPrice": None}

    def on_tick(self, symbol: str, bid: float, ask: float) -> list[dict]:
        events: list[dict] = []
        for ticket, order in list(self._pending.items()):
            if order["symbol"] != symbol:
                continue
            entry = order["entry"]
            side, typ = order["side"], order["orderType"]
            triggered = (
                (side == "buy" and typ == "limit" and ask <= entry)
                or (side == "sell" and typ == "limit" and bid >= entry)
                or (side == "buy" and typ == "stop" and ask >= entry)
                or (side == "sell" and typ == "stop" and bid <= entry)
            )
            if not triggered:
                continue
            fill = ask if side == "buy" else bid
            self._positions[ticket] = {
                "ticket": ticket, "symbol": symbol, "side": side, "lots": order["lots"],
                "entry": fill, "market": fill, "sl": order["sl"], "tp": order["tp"],
                "pnl": 0.0, "mode": "paper", "clientOrderId": order["clientOrderId"],
                "contractSize": order["contractSize"],
            }
            del self._pending[ticket]
            events.append({"type": "fill", **self._positions[ticket]})

        for ticket, pos in list(self._positions.items()):
            if pos["symbol"] != symbol:
                continue
            market = bid if pos["side"] == "buy" else ask
            sign = self._side_sign(pos["side"])
            pos["market"] = market
            pos["pnl"] = (market - pos["entry"]) * sign * pos["contractSize"] * pos["lots"]
            hit = None
            if pos["sl"]:
                hit = "Stop" if ((sign > 0 and bid <= pos["sl"]) or (sign < 0 and ask >= pos["sl"])) else None
            if hit is None and pos["tp"]:
                hit = "Target" if ((sign > 0 and bid >= pos["tp"]) or (sign < 0 and ask <= pos["tp"])) else None
            if hit:
                closed = dict(pos)
                closed["reason"] = hit
                closed["exit"] = market
                events.append({"type": "close", **closed})
                del self._positions[ticket]
        if events or any(v.get("symbol") == symbol for v in self._positions.values()):
            self._persist()
        return events

    def positions(self, symbol: str | None = None) -> list[dict]:
        rows = [dict(v) for v in self._positions.values()]
        return [r for r in rows if r["symbol"] == symbol] if symbol else rows

    def pending(self, symbol: str | None = None) -> list[dict]:
        rows = [dict(v) for v in self._pending.values()]
        return [r for r in rows if r["symbol"] == symbol] if symbol else rows

    def close_position(self, ticket: int, lots: float | None = None) -> dict:
        if ticket not in self._positions:
            raise KeyError("Paper position not found")
        pos = self._positions[ticket]
        close_lots = float(pos["lots"] if lots is None else lots)
        if close_lots <= 0 or close_lots > float(pos["lots"]):
            raise ValueError("Invalid close volume")
        fraction = close_lots / float(pos["lots"])
        realized = float(pos.get("pnl", 0.0)) * fraction
        result = {
            **dict(pos),
            "exit": float(pos.get("market", pos["entry"])),
            "closedLots": close_lots,
            "pnl": realized,
            "reason": "Manual close",
        }
        remaining = float(pos["lots"]) - close_lots
        if remaining <= 1e-12:
            del self._positions[ticket]
        else:
            pos["lots"] = remaining
            pos["pnl"] = float(pos.get("pnl", 0.0)) - realized
        self._persist()
        return result

    def protect_position(self, ticket: int, *, sl: float | None = None, tp: float | None = None,
                         breakeven: bool = False) -> dict:
        if ticket not in self._positions:
            raise KeyError("Paper position not found")
        pos = self._positions[ticket]
        if breakeven:
            pos["sl"] = float(pos["entry"])
        elif sl is not None:
            pos["sl"] = float(sl)
        if tp is not None:
            pos["tp"] = float(tp)
        self._persist()
        return dict(pos)

    def cancel_pending(self, ticket: int) -> dict:
        if ticket not in self._pending:
            raise KeyError("Paper pending order not found")
        order = self._pending.pop(ticket)
        self._persist()
        return order

    def flatten(self, symbol: str | None = None) -> tuple[int, int]:
        pos_ids = [k for k, v in self._positions.items() if symbol is None or v["symbol"] == symbol]
        ord_ids = [k for k, v in self._pending.items() if symbol is None or v["symbol"] == symbol]
        for k in pos_ids:
            del self._positions[k]
        for k in ord_ids:
            del self._pending[k]
        self._persist()
        return len(pos_ids), len(ord_ids)


def spec_payload(spec: SymbolSpec) -> dict:
    return asdict(spec)

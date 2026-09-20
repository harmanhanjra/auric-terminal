"""Serialized, durable MT5 execution and account-wide risk supervision."""
import asyncio
import hashlib
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR

from execution_v2 import choose_filling, normalize_price, spec_from_info
from mt5_data import checked_tick


class AutonomousExecutor:
    def __init__(self, mt5, ledger, magic, guard):
        self.mt5, self.ledger, self.magic, self.guard = mt5, ledger, magic, guard
        self.lock = asyncio.Lock()
        self.last = {"status": "waiting", "reason": "Waiting for MT5"}

    async def call(self, method, *args, **kwargs):
        value = await asyncio.to_thread(getattr(self.mt5, method), *args, **kwargs)
        if value is None:
            raise ValueError(f"MT5 {method} unavailable; execution blocked")
        return value

    async def submit(self, engine, side, distance, bar):
        async with self.lock:
            try:
                result = await self._submit(engine, side, distance, bar)
                self.last = {"status": "filled", "symbol": engine.symbol, "ticket": result.order}
                return result
            except Exception as exc:
                self.last = {"status": "blocked", "symbol": engine.symbol, "reason": str(exc)}
                raise

    async def _submit(self, engine, side, distance, bar):
        m, symbol = self.mt5, engine.symbol
        if self.ledger.unresolved():
            raise ValueError("Unresolved order outcome; broker reconciliation required")
        if side not in (-1, 1) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("Invalid signal or stop distance")
        gate = self.guard(symbol)
        if not gate["allowed"]:
            raise ValueError(gate["reason"])
        terminal = await self.call("terminal_info")
        account = await self.call("account_info")
        if not terminal.connected or not terminal.trade_allowed or getattr(terminal, "tradeapi_disabled", True):
            raise ValueError("MT5 connection or algorithmic trading permission unavailable")
        if not account.trade_allowed or not account.trade_expert:
            raise ValueError("Account does not permit automated trading")
        equity = float(account.equity)
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("Invalid account equity")
        account_key = f"risk:{account.login}:{account.server}"
        checkpoint = self.ledger.state(account_key) or {"peak": equity, "halted": False}
        checkpoint["peak"] = max(checkpoint["peak"], equity)
        drawdown = (checkpoint["peak"] - equity) / checkpoint["peak"] * 100
        if drawdown >= float(os.getenv("MAX_EQUITY_DRAWDOWN_PCT", "5")):
            checkpoint["halted"] = True
        self.ledger.state(account_key, checkpoint)
        if checkpoint["halted"]:
            raise ValueError("Persistent account drawdown halt; operator review required")
        info = await self.call("symbol_info", symbol)
        if info.trade_mode != getattr(m, "SYMBOL_TRADE_MODE_FULL", 4):
            raise ValueError("Symbol is not fully tradable")
        for field in ("point", "trade_tick_size", "volume_min", "volume_max", "volume_step"):
            value = float(getattr(info, field, 0))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid broker specification: {field}")
        spec = spec_from_info(symbol, info)
        tick = await self.call("symbol_info_tick", symbol)
        bid, ask, _ = checked_tick(tick, float(os.getenv("MAX_TICK_AGE_SECONDS", "15")))
        if (ask - bid) / spec.point > engine.max_spread_points:
            raise ValueError("Spread exceeds symbol limit")
        positions = list(await self.call("positions_get"))
        orders = list(await self.call("orders_get"))
        # One independent strategy position per symbol, including manual exposure.
        if any(p.symbol == symbol for p in positions + orders):
            raise ValueError("Symbol already has an open position or pending order")
        if len(positions) + len(orders) >= int(os.getenv("MAX_PORTFOLIO_POSITIONS", "3")):
            raise ValueError("Portfolio position limit reached")
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = list(await self.call("history_deals_get", start, now))
        pnl = sum(sum(float(getattr(d, k, 0) or 0) for k in ("profit", "commission", "swap", "fee"))
                  for d in deals if getattr(d, "type", -1) in (0, 1))
        floating = sum(float(p.profit) + float(getattr(p, "swap", 0)) for p in positions)
        if pnl + floating <= -engine.max_daily_loss:
            engine.risk.kill()
            raise ValueError("Account daily loss limit reached (realized + floating)")
        entries = [d for d in deals if getattr(d, "magic", None) == self.magic and getattr(d, "entry", -1) in (0, 2)]
        if len({d.order for d in entries}) >= int(os.getenv("MAX_DAILY_TRADES", "10")):
            raise ValueError("Daily trade limit reached")
        exits = sorted([d for d in deals if getattr(d, "magic", None) == self.magic and getattr(d, "entry", -1) in (1, 2, 3)],
                       key=lambda d: d.time, reverse=True)
        losses = 0
        for deal in exits:
            net = sum(float(getattr(deal, k, 0) or 0) for k in ("profit", "commission", "swap", "fee"))
            if net >= 0:
                break
            losses += 1
        if losses >= int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3")):
            raise ValueError("Daily consecutive-loss limit reached")
        if exits:
            latest = exits[0]
            latest_net = sum(float(getattr(latest, k, 0) or 0)
                             for k in ("profit", "commission", "swap", "fee"))
            if latest_net < 0 and now.timestamp() - latest.time < float(os.getenv("LOSS_COOLDOWN_SECONDS", "900")):
                raise ValueError("Cooling down after a losing trade")
        price = normalize_price(ask if side == 1 else bid, spec)
        distance = max(distance, info.trade_stops_level * spec.point + ask - bid + 2 * spec.tick_size)
        stop = normalize_price(price - side * distance, spec)
        target = normalize_price(price + side * distance * engine.config["rr"], spec)
        typ = m.ORDER_TYPE_BUY if side == 1 else m.ORDER_TYPE_SELL
        per_lot = abs(float(await self.call("order_calc_profit", typ, symbol, 1.0, price, stop)))
        if not math.isfinite(per_lot) or per_lot <= 0 or stop <= 0 or target <= 0:
            raise ValueError("Invalid broker stop-risk calculation")
        pct = min(float(engine.config["risk_pct"]), float(os.getenv("MAX_TRADE_RISK_PCT", "0.5")))
        budget = equity * pct / 100
        raw = min(budget / per_lot, engine.max_lot, spec.volume_max)
        step = Decimal(str(spec.volume_step))
        volume = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
        if volume < spec.volume_min or volume * per_lot > budget + 1e-6:
            raise ValueError("Minimum broker lot exceeds risk budget")
        open_risk = 0.0
        for p in positions:
            if not p.sl:
                raise ValueError("Portfolio contains an unprotected position")
            ptyp = m.ORDER_TYPE_BUY if p.type == m.POSITION_TYPE_BUY else m.ORDER_TYPE_SELL
            loss = await self.call("order_calc_profit", ptyp, p.symbol, p.volume, p.price_current, p.sl)
            open_risk += max(0.0, -float(loss))
        if orders:
            raise ValueError("Pending portfolio exposure must be resolved before autonomous entry")
        if open_risk + volume * per_lot > equity * float(os.getenv("MAX_PORTFOLIO_RISK_PCT", "2")) / 100:
            raise ValueError("Portfolio stop-risk limit reached")
        margin = float(await self.call("order_calc_margin", typ, symbol, volume, price))
        if not math.isfinite(margin) or margin < 0 or margin > float(account.margin_free) * 0.5:
            raise ValueError("Insufficient free margin reserve")
        identity = f"auto:{account.login}:{account.server}:{symbol}:{engine.config['timeframe']}:{bar}"
        comment = "AU-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        request = dict(action=m.TRADE_ACTION_DEAL, symbol=symbol, volume=volume, type=typ,
                       price=price, sl=stop, tp=target, magic=self.magic, comment=comment,
                       deviation=int(os.getenv("MAX_SLIPPAGE_POINTS", "20")),
                       type_time=m.ORDER_TIME_GTC, type_filling=choose_filling(m, spec))
        check = await self.call("order_check", request)
        if check.retcode != 0:
            raise ValueError(f"Broker preflight: {check.comment}")
        fresh_bid, fresh_ask, _ = checked_tick(await self.call("symbol_info_tick", symbol))
        if abs((fresh_ask if side == 1 else fresh_bid) - price) > request["deviation"] * spec.point:
            raise ValueError("Quote moved beyond slippage limit during preflight")
        gate = self.guard(symbol)
        if not gate["allowed"]:
            raise ValueError(gate["reason"])
        if not self.ledger.reserve(identity, symbol, "live", "market", request):
            raise ValueError("This signal was already submitted; awaiting broker reconciliation")
        # Never retry an ambiguous send. The reservation survives crashes/restarts.
        result = await asyncio.to_thread(m.order_send, request)
        done = (m.TRADE_RETCODE_DONE, getattr(m, "TRADE_RETCODE_DONE_PARTIAL", 10010))
        if result is None or result.retcode not in done:
            if result is not None and result.retcode not in (10008, 10012, 10031):
                self.ledger.fail(identity, str(getattr(result, "comment", "Broker rejection")))
            raise ValueError(f"Order outcome requires reconciliation: {getattr(result, 'comment', 'no response')}")
        self.ledger.complete(identity, dict(volume=result.volume, price=result.price, retcode=result.retcode), result.order)
        engine.journal.add(mode="live", symbol=symbol, side="buy" if side == 1 else "sell",
                           lots=result.volume, entry=result.price, strategy=engine.config["strategy"],
                           reason="Autonomous MT5 execution", raw={**request, "ticket": result.order})
        return result

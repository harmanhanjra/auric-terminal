# Architecture

```text
Browser terminal
  ├─ WebSocket /ws/market ───────────────┐
  ├─ Orders / risk / kill switch         │
  ├─ Strategy catalog / backtests        │
  └─ Account / positions / journal       │
                                          ▼
FastAPI gateway ── normalized quote bus ── Market source adapter
  ├─ RiskManager                           ├─ MetaTrader 5 terminal
  ├─ Strategy + sizing engine              ├─ Twelve Data REST
  ├─ Backtest / optimize / Monte Carlo     └─ labelled demo fallback
  ├─ MT5 order adapter
  └─ SQLite journal
```

## Trust boundaries

1. Browser input is untrusted; order and risk constraints are rechecked server-side.
2. API keys and MT5 credentials remain server-side.
3. Live execution is disabled unless an environment variable explicitly enables it.
4. The browser must also be switched from PAPER to LIVE.
5. The risk manager can halt new entries independently of the UI.
6. The kill endpoint halts the engine before attempting cancellation and liquidation.

## Scaling path

Replace in-process WebSocket fan-out with Redis pub/sub, SQLite with PostgreSQL, OHLC storage with TimescaleDB, and in-process backtests with a bounded worker queue. Add a reconciliation worker that continuously compares local orders, broker deals and positions.

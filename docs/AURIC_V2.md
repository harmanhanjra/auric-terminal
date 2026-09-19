# Auric Terminal V2

Auric V2 separates manual execution from autonomous execution and moves broker-specific
math and paper execution into a dedicated execution layer.

## Execution model

- Manual paper/live selection never arms or disarms an algorithm.
- Manual real orders require ENABLE_LIVE_TRADING=true.
- Autonomous real orders require ENABLE_AUTO_LIVE_TRADING=true.
- Live mutations fail closed without AURIC_LIVE_API_KEY.
- Strategies evaluate the latest closed candle, never the still-forming MT5 candle.
- Every order is normalized to broker tick size, digits, volume step and volume limits.
- MT5 order_check runs before order_send for manual and autonomous entries.
- client_order_id is persisted in SQLite and rejected on duplicate submission.

## Paper broker

Paper mode now tracks market positions, limit/stop pending orders, SL/TP exits,
mark-to-market P/L and a global flatten/cancel operation. It is no longer only a
journal write.

## Risk

Risk sizing uses trade tick size/value and contract metadata instead of a Gold-only
100 oz assumption. Spread guards are measured in broker points and may be configured
per instrument:

- MAX_SPREAD_POINTS_XAUUSD=80
- MAX_SPREAD_POINTS_BTCUSD=1500
- MAX_SPREAD_POINTS_EURUSD=30

The global kill switch halts every Auric engine and, by default, targets every
Auric-managed position and pending order.

## UI

The V2 interface has a broker-aware risk ticket, real market/limit/stop order inputs,
per-symbol autopilot controls, separate manual and auto execution status, dynamic
engine events and an explicitly labelled synthetic liquidity ladder.

## Remaining production work

Before public exposure or material capital: add full user authentication/RBAC, a real
secret manager, an independent broker reconciliation worker, verified economic-news
blackout rules, persistent production databases/streaming infrastructure, and a
Windows + MT5 demo integration test environment.

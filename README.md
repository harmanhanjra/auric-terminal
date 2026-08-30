# AuricTerminal — All-Phase MVP

AuricTerminal is a responsive XAU/USD trading-terminal MVP with normalized live data, guarded MT5 execution, 19 signal strategies, 7 position-sizing models, event-driven backtesting, optimization, Monte Carlo analysis, risk controls, a kill switch and a SQLite trade journal.

> This is a functional engineering MVP, not a certified production brokerage system. Use an MT5 demo account first. Do not expose the gateway publicly without authentication, TLS, secret management, durable idempotency and operational monitoring.

## Phase status

### Phase 1 — UI and chart
- Desktop terminal shell and mobile monitoring view
- Canvas candlesticks and EMA overlay
- Timeframe, order, position, depth and strategy surfaces
- Strategy catalog and backtest workspaces

### Phase 2 — Orders, paper mode and risk
- Paper order endpoint and journal recording
- Lot, exposure, position-count and spread guards
- Paper/live mode separation
- Hold-to-activate kill switch

### Phase 3 — strategy engine
- 19 executable signal modules: trend, mean reversion, market structure, session breakouts and a multi-factor Momentum + Breadth + Volatility model
- 7 sizing models: fixed lot, fixed fractional, ATR risk, capped martingale, anti-martingale, quarter Kelly and grid/DCA exposure control
- Human-readable signal reasons
- Parameter dictionaries suitable for JSON import/export and future visual-composer persistence

### Phase 4 — backtesting and analytics
- Event-driven backtester with spread, slippage, commission, ATR stops and R-multiple targets
- Equity curve, drawdown, win rate, profit factor, expectancy, Sharpe and Sortino
- Parameter-grid optimization endpoint
- Monte Carlo simulation and risk-of-ruin output

### Phase 5 — live bridge and journal
- Source priority: MT5 → Twelve Data → clearly labelled demo feed
- WebSocket tick normalization and reconnect handling
- MT5 account and position synchronization endpoints
- Opt-in MT5 order execution
- MT5 position liquidation and pending-order cancellation through the kill switch
- SQLite trade journal and journal API
- Docker path for web-data/paper deployment

## Web UI (React + TypeScript + Vite)

The primary UI is a modern production web app in `web/`, built with **React 19, TypeScript, Vite, Tailwind CSS, TanStack Query, and lightweight-charts**. It talks to the FastAPI gateway above.

### Run in development (hot reload)

```bash
# Terminal A — start the API gateway
uvicorn server:app --host 127.0.0.1 --port 8000

# Terminal B — start Vite dev server (proxies /api + /ws to :8000)
cd web
npm install
npm run dev        # open http://127.0.0.1:5173
```

### Production build (served by FastAPI)

```bash
cd web
npm run build      # emits web/dist
# Backend now serves the built app at http://127.0.0.1:8000/
```

## Quick start — demo feed

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. If no provider is configured, the UI shows `Demo · start server` or `Demo`; this is never presented as live broker data.

## Twelve Data setup

```bash
cp .env.example .env
```

```env
MARKET_DATA_SOURCE=twelvedata
TWELVE_DATA_API_KEY=your_key
TWELVE_DATA_SYMBOL=XAU/USD
ENABLE_LIVE_TRADING=false
```

Run:

```bash
uvicorn server:app --host 127.0.0.1 --port 8000 --env-file .env
```

Twelve Data supplies quotes and historical OHLC data. It does not execute orders.

## MetaTrader 5 setup

The official MetaTrader5 Python package requires Windows with the MT5 desktop terminal installed and logged in.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install MetaTrader5
copy .env.example .env
```

Configure `.env`:

```env
MARKET_DATA_SOURCE=mt5
MT5_SYMBOL=XAUUSD
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
ENABLE_LIVE_TRADING=false
MAX_LOT=0.20
MAX_DAILY_LOSS=500
```

Start the gateway and validate quotes, account data, symbol precision, filling mode and paper orders against an MT5 demo account. Only after validation should `ENABLE_LIVE_TRADING=true` be considered.

## Main API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Connection and execution status |
| GET | `/api/quote` | Latest normalized XAU/USD quote |
| WS | `/ws/market` | Streaming normalized ticks |
| GET | `/api/candles` | Historical Twelve Data candles |
| GET | `/api/strategies` | Strategy and sizing catalog |
| POST | `/api/backtest` | Event-driven strategy test |
| POST | `/api/optimize` | Parameter-grid optimization |
| POST | `/api/monte-carlo` | Resampled trade simulations |
| GET | `/api/account` | MT5 account snapshot |
| GET | `/api/positions` | MT5 XAU/USD positions |
| POST | `/api/orders` | Paper or guarded live order |
| POST | `/api/kill` | Halt, cancel orders and flatten positions |
| POST | `/api/risk/reset` | Deliberately reset a halted engine |
| GET | `/api/journal` | Recent journal entries |
| GET | `/api/kronos/status` | Kronos engine + dataset availability |
| GET | `/api/kronos/datasets` | Local OHLCV datasets found on disk |
| POST | `/api/kronos/forecast` | OHLC forecast via the Kronos model |

## Kronos AI forecasting

Kronos is a foundation model for financial candlesticks (K-line sequences), cloned from [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) into `kronos/`. The backend exposes a local-data forecast endpoint and the web UI has a **Kronos AI** panel in the left rail.

### One-time setup

```bash
pip install -r kronos/requirements.txt
# CPU-only torch (smaller download; GPU optional):
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Run a forecast

The bundled dataset `kronos/finetune_csv/data/HK_ali_09988_kline_5min_all.csv` (~94k 5-min Alibaba-HK bars) is auto-discovered. Start the gateway, open the web UI, and select **Kronos AI** in the rail:

```bash
uvicorn server:app --host 127.0.0.1 --port 8000
```

Or call the API directly:

```bash
curl -X POST http://127.0.0.1:8000/api/kronos/forecast \
  -H "Content-Type: application/json" \
  -d '{"dataset":"HK_ali_09988_kline_5min_all.csv","lookback":200,"pred_len":40,"model":"mini","T":0.8,"top_p":0.9,"sample_count":2}'
```

- Models: `mini` (4.1M), `small` (24.7M), `base` (102M) — downloaded from Hugging Face on first use (`NeoQuasar/Kronos-*`).
- Drop any `timestamps,open,close,high,low,volume,amount` CSV into `kronos/finetune_csv/data/` and it appears in the dataset picker.
- First run downloads model weights (~30s); inference runs on CPU by default. Override the default model with `KRONOS_MODEL=small`.

## Docker — web data and paper trading

```bash
docker build -t auric-terminal .
docker run --rm -p 8000:8000 -e TWELVE_DATA_API_KEY=your_key auric-terminal
```

Run directly on the Windows MT5 host for broker execution; the supplied Linux container is for web data and paper mode.

## Production hardening still required

Before trading material capital, add Supabase/OIDC authentication and RBAC, PostgreSQL/TimescaleDB persistence, Redis fan-out, encrypted secret storage, CSRF protection, request signing, durable order idempotency, daily-P&L reconstruction from broker history, news-calendar enforcement, full automated tests, broker-specific filling-mode negotiation, observability/alerts and an independent deployment review.

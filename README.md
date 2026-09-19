# AuricTerminal V2 — Manual + Autonomous Trading Workstation

Multi-asset trading workstation for XAUUSD, BTCUSD and EURUSD with broker-aware manual
execution, a real paper broker, guarded autonomous engines, durable order idempotency,
risk-based sizing, research/backtesting, Kronos confirmation, WebSocket data and Electron desktop packaging.

V2 details are documented in docs/AURIC_V2.md.

> **Safety first.** This is a functional engineering MVP, **not** a certified brokerage system.
> It has **no login/auth, no rate limiting, and local-only secret storage**.
> Run it on `127.0.0.1`, start with a **demo account**, keep `ENABLE_LIVE_TRADING=false`
> until you have paper-tested, and never expose it to the public internet without
> authentication, TLS, and secret management in front of it.

## Architecture

```
web/ (React 19 + TS + Vite + Tailwind) ──/api + /ws──▶ server.py (FastAPI gateway)
                                                      ├── engine.py        strategies / sizing / backtest
                                                      ├── multi_engine.py  per-symbol auto-engines
                                                      ├── brain_agent.py   setup-analysis heuristics
                                                      ├── kronos_engine.py optional AI forecast (torch)
                                                      └── auric.db         SQLite journal (git-ignored)
```

Data priority: **MT5 → Twelve Data → Yahoo → clearly-labelled Demo feed**.
Manual live orders require `ENABLE_LIVE_TRADING=true`; autonomous live orders additionally require `ENABLE_AUTO_LIVE_TRADING=true`.

## Prerequisites

| Component | Version | Notes |
|---|---|---|
| Python | 3.12 | Backend gateway |
| Node.js | 20+ (tested 22) | Web UI + Electron |
| MT5 terminal | Windows only | Required for broker data/execution; `MetaTrader5` pip package |
| Docker | optional | Linux container = web data + paper mode only (no MT5) |

## 1. Quick start — demo feed (2 min)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env        # Windows  |  cp .env.example .env on macOS/Linux
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. With no provider configured the header shows
`Demo` — synthetic data, never presented as live.

Dev loop with hot reload:

```bash
# Terminal A — API
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
# Terminal B — web UI (proxies /api + /ws to :8000)
cd web && npm install && npm run dev   # → http://127.0.0.1:5173
```

Production web build (served by FastAPI at `/`):

```bash
cd web && npm install && npm run build   # emits web/dist
uvicorn server:app --host 127.0.0.1 --port 8000
```

## 2. Twelve Data setup (web quotes + candles)

```bash
cp .env.example .env
```

```env
MARKET_DATA_SOURCE=twelvedata
TWELVE_DATA_API_KEY=your_key
TWELVE_DATA_SYMBOL=XAU/USD
ENABLE_LIVE_TRADING=false
```

```bash
uvicorn server:app --host 127.0.0.1 --port 8000 --env-file .env
```

Twelve Data supplies quotes/candles only. It never executes orders.

## 3. MetaTrader 5 setup (Windows)

```powershell
py -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
pip install MetaTrader5
copy .env.example .env
```

`.env`:

```env
MARKET_DATA_SOURCE=mt5
MT5_SYMBOL=XAUUSD
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=Broker-Server
ENABLE_LIVE_TRADING=false     # keep false until validated on demo
AURIC_LIVE_API_KEY=generate-a-long-random-secret
MAX_LOT=0.20
MAX_DAILY_LOSS=500
```

Start the gateway and validate quotes, account data, symbol precision, filling mode and paper orders against an MT5 demo account. Only after validation should `ENABLE_LIVE_TRADING=true` be considered. Live order and live kill-switch requests also require the `X-Auric-Key` header to match `AURIC_LIVE_API_KEY`; if the key is not configured, live mutations fail closed.

## 4. Docker (web data + paper mode)

```bash
cd web && npm install && npm run build && cd ..
docker build -t auric-terminal .
docker run --rm -p 8000:8000 -e TWELVE_DATA_API_KEY=your_key auric-terminal
```

The Linux image cannot run MT5 — run natively on the Windows MT5 host for execution.

## 5. Electron desktop app (Windows installer)

`electron/` is a thin shell: it spawns `python run_server.py` on
`127.0.0.1:8000`, waits for `/api/health`, and shows the built UI.
Same-origin, so no CORS changes needed. Requires Python + deps on the machine
(full Python bundling via PyInstaller is out of scope for this MVP).

```bash
cd web && npm install && npm run build && cd ..
cd electron && npm install && npm start        # dev run
npm run dist:win                               # → installer in electron/dist
```

Env overrides: `AURIC_BACKEND_URL` (use an existing backend),
`AURIC_PORT` (default 8000), `AURIC_PYTHON` (default `python`),
`AURIC_NO_SPAWN=1` (never spawn).

## Configuration reference

All settings are env vars (see `.env.example`). Key ones:

| Var | Default | Purpose |
|---|---|---|
| `MARKET_DATA_SOURCE` | `auto` | `auto`/`mt5`/`twelvedata`/`web` |
| `ENABLE_LIVE_TRADING` | `false` | Manual real-order gate |
| `ENABLE_AUTO_LIVE_TRADING` | `false` | Separate autonomous real-order gate |
| `MAX_LOT` / `MAX_DAILY_LOSS` | `1.0` / `500.0` | Server-side risk caps |
| `ENGINE_*` | see `.env.example` | Auto-engine strategy/timeframe/risk/trail/pyramid |
| `ENGINE_KRONOS_CONFIRM`, `KRONOS_*` | `true`, … | AI veto/confirm filter tuning |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | Entry/kill notifications; **never commit real values** |
| `AURIC_LIVE_API_KEY` | empty | Required `X-Auric-Key` for live order/kill requests; fail-closed if unset |

## Main API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Connection + execution status |
| GET | `/api/quote` | Latest normalized XAU/USD quote |
| WS | `/ws/market` | Streaming normalized ticks |
| GET | `/api/candles?symbol=&interval=&outputsize=` | MT5 → Yahoo → Demo candles |
| GET | `/api/strategies` | Strategy + sizing catalog |
| POST | `/api/backtest` | Event-driven strategy test |
| POST | `/api/optimize` | Parameter-grid optimization (≤250 combos) |
| POST | `/api/monte-carlo` | Resampled trade simulations |
| GET | `/api/account` | MT5 account snapshot |
| GET | `/api/positions?mode=paper|live|all` | Paper and/or MT5 positions |
| GET | `/api/pending` | Auric pending orders |
| POST | `/api/risk/preview` | Broker-aware risk/lot/margin preview |
| POST | `/api/orders` | Idempotent market/limit/stop paper or live order |
| POST | `/api/kill` | Global-by-default halt, cancel and flatten |
| POST | `/api/risk/reset` | Reset a halted engine |
| GET | `/api/journal` | Recent journal entries |
| GET | `/api/symbols` | All per-symbol engine states |
| GET/POST | `/api/symbols/{sym}/…` | Per-symbol quote/trades/metrics/start/stop |
| GET | `/api/kronos/status`, `/api/kronos/datasets` | AI engine availability |
| POST | `/api/kronos/forecast` | OHLC forecast from a local CSV dataset |

## Kronos AI forecasting (optional)

```bash
pip install -r kronos/requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open the **Kronos AI** rail panel, or call directly:

```bash
curl -X POST http://127.0.0.1:8000/api/kronos/forecast \
  -H "Content-Type: application/json" \
  -d '{"dataset":"HK_ali_09988_kline_5min_all.csv","lookback":200,"pred_len":40,"model":"mini","T":0.8,"top_p":0.9,"sample_count":2}'
```

Models `mini`/`small`/`base` download from Hugging Face on first use.
Drop `timestamps,open,close,high,low,volume,amount` CSVs into
`kronos/finetune_csv/data/` to add datasets.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q   # 74 tests: engine + gateway
```

## Production hardening — still required

Do these before material capital or any public exposure:

- [ ] AuthN/Z: OIDC/Supabase login + RBAC in front of every `/api/*`
- [ ] Secrets: vault/secret-manager for MT5 + Telegram creds; **rotate the Telegram
      bot token that was previously stored in plaintext `.env`**
- [ ] Persistence: PostgreSQL/TimescaleDB for journal, Redis fan-out for ticks
- [x] Idempotency: durable `client_order_id` dedupe in SQLite
- [x] Broker details: symbol precision/volume/filling normalization and order preflight
- [ ] Broker reconciliation worker + verified economic-news calendar guard
- [ ] Ops: reverse-proxy TLS, rate limits, structured logs/alerts, backup/restore drill
- [ ] Release: `npm audit` + `pip-audit`, full test suite green, independent deploy review

## Troubleshooting

| Symptom | Fix |
|---|---|
| Header shows `Demo` | No MT5/Twelve Data configured — set `.env` and restart |
| `MT5 terminal is not connected` | Windows + logged-in MT5 terminal + `pip install MetaTrader5` required |
| `pip install` fails on numpy | Use the pinned `numpy==2.2.6` in `requirements.txt` (there is no 2.5.1) |
| Docker has no live trades | By design — Linux image is data/paper only; run on the MT5 host |
| Electron says backend unreachable | `pip install -r requirements.txt`, or point `AURIC_BACKEND_URL` at a running gateway |
| Port 8000 busy | `uvicorn server:app --port 8001` (+ `AURIC_PORT=8001` for Electron) |

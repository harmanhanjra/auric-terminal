# Auric Terminal V3 — Production Operations Runbook

Auric V3 is a production-oriented **single-node** trading workstation. The safest state is the default and real execution requires multiple independent gates.

## Execution promotion

The persisted runtime stages are:

1. **shadow** — strategies/models evaluate signals; no simulated or real entry.
2. **paper** — strategy/manual orders use the durable paper broker.
3. **assisted** — manual live orders are allowed; autonomous live entries remain blocked.
4. **auto** — autonomous live entries are allowed only when every production prerequisite passes.

Auto promotion is rejected unless autonomous live execution is enabled, the live execution secret is configured, MT5 is connected, the global circuit is clear, production RBAC is configured, and reconciliation has no untracked Auric tickets.

Keep both real-execution environment gates disabled and the execution stage at shadow until demo validation is complete.

## Authentication and secrets

Production mode supports viewer, trader and admin RBAC. API tokens are hashed before being retained in process memory. The UI keeps RBAC and live-execution credentials only in session storage.

Sensitive settings support mounted secret files through the corresponding *_FILE variables, including the live key, MT5 password, Telegram token, market-data key, news-feed key and RBAC-key JSON.

For an internet-facing multi-user service, use an OIDC-aware identity proxy or gateway in front of Auric and keep Auric RBAC as a second application gate.

## Risk and circuit breakers

V3 enforces broker-aware tick/contract math, maximum order size, spread limits, maximum risk per trade, open-position and exposure caps, margin thresholds, daily net realized loss, mandatory live stop loss by default, stale-tick rejection, closed-candle autonomous signals, and a persistent global circuit breaker.

Risk-reducing actions — close, partial close, cancel pending, modify protection and breakeven — remain available while the circuit is halted.

## Broker reconciliation

The reconciliation worker compares active Auric-magic MT5 positions/orders with broker tickets stored in the durable execution ledger. Manual and autonomous live entries are both ledgered.

While Auto is active, Auric can halt automatically on MT5 disconnect, untracked broker tickets, or reconciliation errors.

## Economic-calendar guard

News-event blackout windows are persisted in SQLite and can veto new live risk by impact and symbol. Events can be entered manually or synchronized from a normalized HTTP feed. The normalized feed should return an events array whose items contain title, impact, start_ms, end_ms, symbols and optional source fields.

Use a provider adapter or n8n workflow when the upstream economic calendar uses another schema.

## Durability and backups

Set AURIC_DB_PATH to durable storage. The database contains journal records, order idempotency, paper positions/orders, circuit state, audit events, news windows and reconciliation snapshots.

Online SQLite backups run at the configured interval with retention. Operators can also trigger a backup from the V3 control panel.

The production container stores state under /app/data and exposes it as a volume.

## Deployment

The Docker image is multi-stage, builds the web frontend, runs the Python runtime as a non-root user and exposes a healthcheck. It deliberately uses one Uvicorn worker because this workstation owns a single local broker/control state.

For HTTPS use deploy/Caddyfile.example or an equivalent reverse proxy. Do not expose raw port 8000 directly to the public internet.

Native MT5 execution still requires a compatible Windows MT5 host. Linux containers are suitable for paper/research/control-plane deployments but cannot natively drive the Windows MetaTrader5 package.

## Release validation

Every V3 release PR runs Python compilation, Python dependency audit, the full pytest suite, npm high-severity audit, frontend lint, TypeScript/Vite production build and a production Docker build.

Before material capital, validate the actual broker symbol aliases, tick values, contract sizes, stop levels and filling modes; test partial close and protection changes on demo; force broker disconnect and reconciliation drift; test a news blackout; restore a generated database backup; and keep sustained shadow/paper evidence before Auto promotion.
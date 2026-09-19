# Auric Production Runbook

Auric V3 is designed as a **single-operator, single-node trading workstation**. It now has
enforceable production controls, but an internet-facing multi-user service should still be placed
behind an audited OIDC/RBAC reverse proxy and a managed secret store.

## Execution promotion

`AURIC_EXECUTION_STAGE` is an independent promotion gate:

| Stage | Signals | Paper execution | Manual live | Autonomous live |
| --- | --- | --- | --- | --- |
| shadow | yes | no | no | no |
| paper | yes | yes | no | no |
| assisted | yes | yes | yes | no |
| auto | yes | yes | yes | yes |

The server also requires `ENABLE_LIVE_TRADING=true` for manual real orders and
`ENABLE_AUTO_LIVE_TRADING=true` for autonomous real orders. These flags do not bypass the stage.

## Minimum production configuration

Use long, independently generated secrets and do not commit them:

```env
AURIC_ENV=production
AURIC_EXECUTION_STAGE=paper
AURIC_REQUIRE_AUTH=true
AURIC_AUTH_SECRET=<32+ random bytes>
AURIC_OPERATOR_USERNAME=operator
AURIC_OPERATOR_PASSWORD=<long unique password>
AURIC_LIVE_API_KEY=<32+ random bytes>

ENABLE_LIVE_TRADING=false
ENABLE_AUTO_LIVE_TRADING=false

MAX_LOT=0.20
MAX_DAILY_LOSS=250
MAX_GROSS_LEVERAGE=2.0
MAX_SYMBOL_NOTIONAL_PCT=100

ECONOMIC_CALENDAR_FILE=C:\\auric\\calendar.json
```

Keep live flags false until the readiness endpoint returns ready and the broker demo environment
has been exercised for the intended symbols.

## Readiness and monitoring

- `GET /api/health` — lightweight liveness and environment summary.
- `GET /api/readiness` — fail-closed production checks. Returns HTTP 503 when a required gate fails.
- `GET /api/production/status` — stage, auth, blackout, reconciliation and portfolio limits.
- `GET /api/reconciliation` — recent broker-ticket reconciliation health.
- `GET /api/metrics` — Prometheus text counters.
- `GET /api/audit` — append-only operator/API audit events.

Use the readiness endpoint for deployment health checks. Do not use only `/api/health` to decide
whether live trading is safe.

## Economic blackout feed

Auric reads a provider-normalized JSON file and hot-reloads it on modification. High/critical events
block new live entries and pyramids for matching symbols. See
`config/economic_calendar.example.json`.

Feed this file from a trusted economic-calendar source. A malformed configured file fails closed for
new live risk.

## Reconciliation

Every 15 seconds (configurable), Auric compares recent live execution ledger tickets against current
MT5 positions/orders and today's broker order/deal history. Unmatched tickets make reconciliation
unhealthy and readiness fails while live trading is configured.

## Incident actions

1. Use **KILL ALL** to halt Auric engines and flatten/cancel Auric-managed broker state.
2. Set both live flags to false and restart.
3. Preserve `auric.db`, logs and the current economic calendar for investigation.
4. Inspect `/api/audit`, `/api/reconciliation`, broker history and execution ledger records.
5. Resolve the root cause in paper mode first.
6. Promote back through paper → assisted → auto rather than jumping directly to auto.

## Backups

Back up `auric.db` while the process is stopped or use SQLite's online backup API. Retain encrypted
copies of audit and execution records according to your operational/legal requirements.

## Network boundary

For the local workstation, bind FastAPI to `127.0.0.1`. If remote access is required, terminate TLS
at a hardened reverse proxy/VPN, restrict source networks, and use OIDC/RBAC at the edge. The built-in
HMAC operator session is intended for a controlled single-operator deployment, not a public multi-user
identity platform.

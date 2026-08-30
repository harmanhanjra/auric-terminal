# AuricTerminal — Archify Maps

Beautiful, verifiable architecture diagrams generated with **Archify** (`tt-a1i/archify` v2.16, installed as `.agents/skills/archify` + `.opencode/skills/archify` + global).

All diagrams are **showcase-validated** (9/9 checks) and self-contained HTML — open and present, no build step.

## Maps

| Diagram | File | What it shows |
|---|---|---|
| **Runtime Architecture** | [`auric-terminal.html`](./auric-terminal.html) | FastAPI gateway, SymbolEngine per symbol, RiskManager + kill-switch, Kronos AI confirm/veto, SQLite journal — trust boundary + execution guard |
| **Simple Runtime** | [`auric-runtime-simple.html`](./auric-runtime-simple.html) | Minimal validated runtime (web-app geometry) |
| **Order & Risk Sequence** | [`auric-sequence.html`](./auric-sequence.html) | Browser → Gateway → Risk → MT5/Journal with Kronos veto, plus paper/live branching and kill-switch flatten |
| **Market Data Flow** | [`auric-dataflow.html`](./auric-dataflow.html) | MT5 / TwelveData / Demo → normalized quote bus → chart, depth, backtest, Kronos, journal |

## Clean / Reliable / Beautiful — what changed

**Clean**
- `server.py:811-888` — unified `/api/journal` (entries + trades alias), removed dead `journal.query` duplicate
- `web/src/index.css` — ink / gold / bull-bear tokens via `@theme`, consistent Tailwind palette
- `web/src/App.tsx` — grid layout ` rail | chart+dock | aside ` (reliable, no nested split bugs)

**Reliable**
- `TopBar.tsx:1-200` — fixed `useEffect` import, `usePriceFlash` via effect (no setState during render), correct `Account` fields (`balance`/`equity`/`freeMargin`), CSS marquee instead of JS ticker loop
- `ChartPanel.tsx` — removed unused import, fixed `api.candles` arity, removed invalid `HeikinAshi` / `lineWidth` props, fixed `quote` shadowing, added `TrendingUp`
- `ResizableSplitPane.tsx:1,41` — type-only `MouseEvent` import + `globalThis.MouseEvent` for window listeners

**Beautiful**
- New palette: `#06080f` ink + `#c9a227` gold + Bloomberg-inspired density, `backdrop-blur`, `card` elevation
- TopBar: 14px height, flash tick (`animate-flash-up/down`), session chip, spread chip, hold-to-kill with arming pulse
- ChartPanel: timeframe/period/type selectors, Studies/Compare/Drawing, lightweight-charts with dark grid, volume pane, OHLC legend
- Verified: `npm run build` ✅ and `pytest` 23/23 ✅

## Re-generate

```bash
node .agents/skills/archify/bin/archify.mjs doctor
node .agents/skills/archify/bin/archify.mjs deliver architecture docs/archify/auric-terminal.architecture.json docs/archify/auric-terminal.html --quality showcase --json
node .agents/skills/archify/bin/archify.mjs deliver sequence docs/archify/auric-sequence.json docs/archify/auric-sequence.html --quality showcase --json
node .agents/skills/archify/bin/archify.mjs deliver dataflow docs/archify/auric-dataflow.json docs/archify/auric-dataflow.html --quality showcase --json
```

Open any `*.html` directly — dark/light (`T`), present (`F`), export PNG/SVG/WebM, guided `?view=…`.

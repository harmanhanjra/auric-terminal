import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { api } from '../lib/api'
import { fmtMoney } from '../lib/format'
import { Modal } from './Modal'

const SIZERS = [
  ['fixed_lot', 'Fixed lot'],
  ['fixed_fractional', 'Fixed fractional'],
  ['atr_risk', 'ATR risk'],
  ['martingale', 'Martingale capped'],
  ['anti_martingale', 'Anti-martingale'],
  ['kelly_quarter', 'Quarter Kelly'],
  ['grid_dca', 'Grid / DCA'],
]

export function BacktestModal() {
  const { data: strategies } = useQuery({
    queryKey: ['strategies'],
    queryFn: api.strategies,
    staleTime: 60_000,
  })
  const { data: candlesData } = useQuery({
    queryKey: ['candles', 'M15'],
    queryFn: () => api.candles('M15', 520),
    staleTime: 60_000,
  })

  const [strategy, setStrategy] = useState('ema144_pullback')
  const [sizer, setSizer] = useState('fixed_fractional')
  const [riskPct, setRiskPct] = useState(1)
  const [capital, setCapital] = useState(10000)

  const mutation = useMutation({
    mutationFn: () =>
      api.backtest({
        candles: candlesData?.values ?? [],
        strategy,
        params: {},
        initial: capital,
        risk_pct: riskPct,
        sizer,
        spread: 0.18,
      }),
  })

  const result = mutation.data
  const metrics = result?.metrics
  const curve = result?.equity_curve ?? []

  const curvePath = useMemo(() => {
    if (curve.length < 2) return null
    const mn = Math.min(...curve)
    const mx = Math.max(...curve)
    const range = mx - mn || 1
    const step = Math.max(1, Math.floor(curve.length / 240))
    const pts = curve
      .filter((_, i) => i % step === 0)
      .map((v, i, a) => `${(i / (a.length - 1)) * 860},${168 - ((v - mn) / range) * 130}`)
      .join(' L')
    return `M ${pts}`
  }, [curve])

  const metricCards = metrics
    ? [
        ['Net P/L', fmtMoney(metrics.net_pnl), metrics.net_pnl >= 0 ? 'text-bull-500' : 'text-bear-500'],
        ['Max DD', `${metrics.max_drawdown_pct.toFixed(2)}%`, 'text-fg-100'],
        ['Win rate', `${metrics.win_rate.toFixed(1)}%`, 'text-fg-100'],
        ['Profit factor', metrics.profit_factor.toFixed(2), metrics.profit_factor >= 1 ? 'text-bull-500' : 'text-bear-500'],
        ['Sharpe', metrics.sharpe.toFixed(2), 'text-fg-100'],
        ['Trades', String(metrics.trades), 'text-fg-100'],
      ]
    : [
        ['Net P/L', '—', ''],
        ['Max DD', '—', ''],
        ['Win rate', '—', ''],
        ['Profit factor', '—', ''],
        ['Sharpe', '—', ''],
        ['Trades', '—', ''],
      ]

  const run = () => {
    if (!candlesData?.values?.length) {
      mutation.mutate()
      return
    }
    mutation.mutate()
  }

  return (
    <Modal
      id="backtest"
      title="Backtest & Optimization"
      subtitle="Event-driven simulation with spread, slippage, risk sizing and Monte Carlo analysis"
      badges={['Walk-forward', 'Monte Carlo', 'Risk of ruin']}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 p-4">
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          className="h-9 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-200 outline-none focus:border-ink-500"
          aria-label="Strategy"
        >
          {(strategies?.strategies ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select
          value={sizer}
          onChange={(e) => setSizer(e.target.value)}
          className="h-9 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-200 outline-none focus:border-ink-500"
          aria-label="Sizer"
        >
          {SIZERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Risk %
          <input
            value={riskPct}
            onChange={(e) => setRiskPct(Number(e.target.value))}
            className="tnum w-12 bg-transparent text-right text-fg-100 outline-none"
            inputMode="decimal"
          />
        </label>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Capital $
          <input
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="tnum w-16 bg-transparent text-right text-fg-100 outline-none"
            inputMode="numeric"
          />
        </label>
        <button
          onClick={run}
          disabled={mutation.isPending}
          className="ml-auto h-9 rounded-md bg-bull-500 px-4 text-[11px] font-bold uppercase tracking-[0.08em] text-white transition-colors hover:bg-bull-400 disabled:opacity-50"
        >
          {mutation.isPending ? 'Running…' : 'Run Backtest'}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-3 lg:grid-cols-6">
        {metricCards.map(([label, value, tone]) => (
          <div key={label} className="flex flex-col gap-1 rounded-lg border border-ink-700 bg-ink-800 p-2.5">
            <span className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">{label}</span>
            <span className={clsx('tnum text-[16px] font-semibold', tone || 'text-fg-100')}>{value}</span>
          </div>
        ))}
      </div>

      <div className="px-4 pb-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-fg-400">Equity Curve</h3>
          <span className="text-[9px] text-fg-500">
            {mutation.isError
              ? 'Backtest failed — no live candle history'
              : mutation.isPending
                ? 'Running event-driven simulation…'
                : result
                  ? `Complete · ${metrics?.trades ?? 0} trades`
                  : 'Ready · sample XAUUSD M15'}
          </span>
        </div>
        <svg
          viewBox="0 0 880 180"
          preserveAspectRatio="none"
          className="h-[150px] w-full rounded-lg border border-ink-700 bg-ink-800"
        >
          <defs>
            <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(22,199,132,0.25)" />
              <stop offset="100%" stopColor="rgba(22,199,132,0)" />
            </linearGradient>
          </defs>
          {curvePath ? (
            <>
              <path d={`${curvePath} L 880,180 L 0,180 Z`} fill="url(#eq-fill)" />
              <path
                d={curvePath}
                fill="none"
                stroke="#16c784"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </>
          ) : (
            <text x="440" y="90" textAnchor="middle" fill="#5a6270" fontSize="11">
              Run a backtest to render the equity curve
            </text>
          )}
        </svg>
      </div>
    </Modal>
  )
}
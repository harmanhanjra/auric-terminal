import { useState, useMemo } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { BrainCircuit } from 'lucide-react'
import { api } from '../lib/api'
import { fmtPrice } from '../lib/format'
import { Modal } from './Modal'

function makeLine(points: { close: number }[], w: number, h: number, padY: number) {
  if (!points?.length || points.length < 2) return ''
  const vals = points.map((p) => p.close)
  const mn = Math.min(...vals)
  const mx = Math.max(...vals)
  const r = mx - mn || 1
  const step = Math.max(1, Math.floor(points.length / 300))
  const usableH = h - padY * 2
  const coords = points
    .filter((_, i) => i % step === 0 || i === points.length - 1)
    .map((p, i, a) => `${(i / (a.length - 1)) * w},${padY + usableH - ((p.close - mn) / r) * usableH}`)
    .join(' L')
  return `M ${coords}`
}

export function KronosModal() {
  const { data: status } = useQuery({
    queryKey: ['kronos-status'],
    queryFn: api.kronosStatus,
    staleTime: 30_000,
  })

  const datasets = status?.datasets ?? []
  const [datasetName, setDatasetName] = useState('')
  const [lookback, setLookback] = useState(200)
  const [predLen, setPredLen] = useState(40)
  const [T, setT] = useState(0.8)
  const [topP, setTopP] = useState(0.9)
  const [model, setModel] = useState('mini')
  const [samples, setSamples] = useState(2)

  const mutation = useMutation({
    mutationFn: () =>
      api.kronosForecast({
        dataset: datasetName || datasets[0]?.name || '',
        lookback,
        pred_len: predLen,
        model,
        T,
        top_p: topP,
        sample_count: samples,
      }),
  })

  const result = mutation.data
  const meta = result?.metadata

  const [histPath, forePath] = useMemo(() => {
    if (!result) return ['', '']
    const w = 860
    const h = 160
    const pad = 14
    return [
      makeLine(result.historical, w, h, pad),
      makeLine([...result.historical.slice(-1), ...result.forecast], w, h, pad),
    ]
  }, [result])

  const dataKey = mutation.submittedAt || 0

  const run = () => {
    const ds = datasetName || datasets[0]?.name
    if (!ds) return
    mutation.mutate()
  }

  return (
    <Modal
      id="kronos"
      title="Kronos AI Forecast"
      subtitle="Foundation model for financial candlesticks — predicts OHLC bars from local data"
      badges={['Local data', 'CPU inference', 'OHLC forecast']}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 p-4">
        <select
          value={(datasetName || datasets[0]?.name) ?? ''}
          onChange={(e) => setDatasetName(e.target.value)}
          className="h-9 max-w-[280px] truncate rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-200 outline-none focus:border-ink-500"
          aria-label="Dataset"
        >
          {datasets.map((d) => (
            <option key={d.name} value={d.name}>
              {d.name} ({(d.size / 1e6).toFixed(2)} MB)
            </option>
          ))}
        </select>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="h-9 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-200 outline-none focus:border-ink-500"
          aria-label="Model"
        >
          <option value="mini">Kronos-mini (4.1M)</option>
          <option value="small">Kronos-small (24.7M)</option>
          <option value="base">Kronos-base (102M)</option>
        </select>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Lookback
          <input
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="tnum w-10 bg-transparent text-right text-fg-100 outline-none"
            inputMode="numeric"
          />
        </label>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Forecast
          <input
            value={predLen}
            onChange={(e) => setPredLen(Number(e.target.value))}
            className="tnum w-10 bg-transparent text-right text-fg-100 outline-none"
            inputMode="numeric"
          />
        </label>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Temp
          <input
            value={T}
            onChange={(e) => setT(Number(e.target.value))}
            className="tnum w-10 bg-transparent text-right text-fg-100 outline-none"
            inputMode="decimal"
            step="0.1"
          />
        </label>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Top-p
          <input
            value={topP}
            onChange={(e) => setTopP(Number(e.target.value))}
            className="tnum w-10 bg-transparent text-right text-fg-100 outline-none"
            inputMode="decimal"
            step="0.05"
          />
        </label>
        <label className="flex h-9 items-center gap-1.5 rounded-md border border-ink-600 bg-ink-800 px-2 text-[11px] text-fg-400">
          Samples
          <input
            value={samples}
            onChange={(e) => setSamples(Number(e.target.value))}
            className="tnum w-8 bg-transparent text-right text-fg-100 outline-none"
            inputMode="numeric"
          />
        </label>
        <button
          onClick={run}
          disabled={mutation.isPending || datasets.length === 0}
          className="ml-auto h-9 rounded-md bg-gold-600 px-4 text-[11px] font-bold uppercase tracking-[0.08em] text-ink-950 transition-colors hover:bg-gold-500 disabled:opacity-50"
        >
          {mutation.isPending ? (
            <span className="flex items-center gap-1.5">
              <BrainCircuit className="h-3.5 w-3.5 animate-pulse" />
              Predicting…
            </span>
          ) : (
            'Run Forecast'
          )}
        </button>
      </div>

      {meta && (
        <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-3">
          {([
            ['Last close', fmtPrice(meta.last_close), 'text-fg-100'],
            ['Forecast close', fmtPrice(meta.forecast_close), 'text-gold-400'],
            [
              'Change %',
              `${meta.pct_change > 0 ? '+' : ''}${meta.pct_change.toFixed(2)}%`,
              meta.pct_change >= 0 ? 'text-bull-500' : 'text-bear-500',
            ],
            ['Model', meta.model, 'text-gold-400'],
            ['Rows', meta.rows.toLocaleString(), 'text-fg-100'],
            ['Horizon', `${meta.lookback} / ${meta.pred_len} bars`, 'text-fg-100'],
          ] as const).map(([label, value, tone]) => (
            <div key={label} className="flex flex-col gap-1 rounded-lg border border-ink-700 bg-ink-800 p-2.5">
              <span className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">{label}</span>
              <span className={clsx('tnum text-[14px] font-semibold', tone)}>{value}</span>
            </div>
          ))}
        </div>
      )}

      {datasets.length === 0 && !status?.ok && (
        <div className="flex flex-col items-center justify-center p-12 text-fg-500">
          <BrainCircuit className="mb-3 h-10 w-10 text-fg-600" />
          <p className="text-[12px]">Kronos engine unavailable</p>
          <p className="mt-1 text-[9px] text-fg-500/50">{status?.reason ?? 'Install torch + pandas'}</p>
        </div>
      )}

      {(result || mutation.isPending) && (
        <div className="px-4 pb-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-fg-400">Forecast Chart</h3>
            <span className="text-[9px] text-fg-500">
              {mutation.isPending
                ? 'Running Kronos autoregressive inference…'
                : mutation.isError
                  ? 'Forecast failed'
                  : result
                    ? `${result.historical.length} hist · ${result.forecast.length} forecast bars`
                    : 'Ready'}
            </span>
          </div>
          <div className="flex h-[180px] w-full overflow-hidden rounded-lg border border-ink-700 bg-ink-800">
            {mutation.isPending ? (
              <div className="flex w-full items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <BrainCircuit className="h-8 w-8 animate-pulse text-gold-400" />
                  <span className="text-[11px] text-fg-400">Running Kronos inference on CPU…</span>
                </div>
              </div>
            ) : mutation.isError ? (
              <div className="flex w-full items-center justify-center text-[11px] text-fg-500">
                Forecast failed — check backend logs
              </div>
            ) : (
              <svg
                key={`kr-${dataKey}`}
                viewBox="0 0 880 180"
                preserveAspectRatio="none"
                className="h-full w-full"
              >
                <defs>
                  <linearGradient id="kr-hist" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(22,199,132,0.18)" />
                    <stop offset="100%" stopColor="rgba(22,199,132,0)" />
                  </linearGradient>
                  <linearGradient id="kr-fore" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(249,184,40,0.15)" />
                    <stop offset="100%" stopColor="rgba(249,184,40,0)" />
                  </linearGradient>
                </defs>
                <path d={`${histPath} L 880,180 L 0,180 Z`} fill="url(#kr-hist)" />
                <path d={histPath} fill="none" stroke="#16c784" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d={`${forePath} L 880,180 L ${(result?.historical?.length ?? 200) / (result?.historical?.length ?? 1) * 860},180 Z`} fill="url(#kr-fore)" opacity="0.6" />
                <path d={forePath} fill="none" stroke="#c9a227" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </div>
          <div className="mt-2 flex gap-4 text-[9px] text-fg-500">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-bull-500" /> Historical
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-gold-400" /> Forecast
            </span>
          </div>
        </div>
      )}

      {!result && !mutation.isPending && !mutation.isError && datasets.length > 0 && (
        <div className="flex flex-col items-center justify-center p-12 text-fg-500">
          <BrainCircuit className="mb-3 h-10 w-10 text-gold-400/40" />
          <p className="text-[12px]">Choose settings and run a forecast</p>
          <p className="mt-1 text-[9px] text-fg-500/50">First run downloads model weights from Hugging Face (~30s)</p>
        </div>
      )}
    </Modal>
  )
}
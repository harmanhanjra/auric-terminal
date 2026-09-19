import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Bot, BrainCircuit, Play, Shield, Square } from 'lucide-react'
import { useState } from 'react'
import { api, ApiError } from '../lib/api'

export function EngineCard({ activeSymbol = 'XAUUSD' }: { activeSymbol?: string }) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['engine', activeSymbol] })
    queryClient.invalidateQueries({ queryKey: ['symbols'] })
  }

  const onError = (e: unknown) => {
    setActionError(e instanceof ApiError ? e.message : 'Engine request failed')
  }

  const startMutation = useMutation({
    mutationFn: () => api.symbolStart(activeSymbol),
    onSuccess: () => { setActionError(null); invalidate() },
    onError,
  })

  const stopMutation = useMutation({
    mutationFn: () => api.symbolStop(activeSymbol),
    onSuccess: () => { setActionError(null); invalidate() },
    onError,
  })

  const { data: engineData } = useQuery({
    queryKey: ['engine', activeSymbol],
    queryFn: () => api.symbolEngine(activeSymbol),
    refetchInterval: 2200,
  })

  const { data: kronosStatus } = useQuery({
    queryKey: ['kronos-status'],
    queryFn: api.kronosStatus,
    staleTime: 30_000,
  })

  const isRunning = engineData?.running ?? false
  const strategyName = (engineData?.strategy || 'ema144_pullback').replace(/_/g, ' ')
  const autoLive = engineData?.config?.autoLive === true || engineData?.autoLiveEnabled === true

  return (
    <section className="border-b border-ink-700/70 bg-ink-900/55 p-3">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={clsx(
            'grid h-7 w-7 place-items-center rounded-md border',
            isRunning ? 'border-bull-500/30 bg-bull-500/10 text-bull-400' : 'border-ink-700 bg-ink-800 text-fg-500',
          )}>
            <Bot className="h-4 w-4" />
          </span>
          <div>
            <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-fg-300">{activeSymbol} Autopilot</div>
            <div className="text-[8px] uppercase tracking-[0.12em] text-fg-600">Closed-bar execution engine</div>
          </div>
        </div>
        <span className={clsx(
          'rounded border px-2 py-1 text-[8px] font-black uppercase tracking-[0.1em]',
          autoLive
            ? 'border-bear-500/35 bg-bear-500/10 text-bear-400'
            : 'border-gold-600/35 bg-gold-600/10 text-gold-300',
        )}>
          {autoLive ? 'AUTO LIVE' : 'PAPER AUTO'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-ink-700/80 bg-ink-950/55 p-2.5 text-[9px]">
        <Metric label="Strategy" value={strategyName.toUpperCase()} />
        <Metric label="Timeframe" value={engineData?.timeframe || 'M15'} accent />
        <Metric label="Risk / trade" value={engineData?.config?.risk_pct != null ? `${engineData.config.risk_pct}%` : '—'} />
        <Metric label="Target R:R" value={engineData?.config?.rr != null ? `1:${engineData.config.rr}` : '—'} />
        <Metric label="Signal" value={engineData?.signal?.side === 1 ? 'BUY' : engineData?.signal?.side === -1 ? 'SELL' : 'SCANNING'} />
        <Metric label="Executions" value={String(engineData?.trades ?? 0)} />
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5">
        <div className="rounded-md border border-ink-700/70 bg-ink-800/45 p-2">
          <div className="flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">
            <Shield className="h-3 w-3" /> Risk gate
          </div>
          <div className={clsx('mt-1 text-[10px] font-bold', engineData?.risk?.halted ? 'text-bear-400' : 'text-bull-400')}>
            {engineData?.risk?.halted ? 'HALTED' : 'NORMAL'}
          </div>
          <div className="mt-0.5 text-[8px] text-fg-600">
            Spread ≤ {engineData?.risk?.maxSpreadPoints ?? '—'} pts
          </div>
        </div>
        <div className="rounded-md border border-ink-700/70 bg-ink-800/45 p-2">
          <div className="flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">
            <BrainCircuit className="h-3 w-3" /> Kronos
          </div>
          <div className="mt-1 text-[10px] font-bold text-fg-300">
            {kronosStatus?.ok ? 'AVAILABLE' : 'OPTIONAL'}
          </div>
          <div className="mt-0.5 text-[8px] text-fg-600">
            {engineData?.signal?.reason ? 'Signal context active' : 'Awaiting signal'}
          </div>
        </div>
      </div>

      {actionError ? (
        <div className="mt-2 rounded-md border border-bear-500/30 bg-bear-500/10 px-2 py-1.5 text-[9px] text-bear-400">
          {actionError}
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-2 gap-2">
        <button
          onClick={() => startMutation.mutate()}
          disabled={isRunning || startMutation.isPending}
          className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-bull-500/30 bg-bull-500/10 text-[9px] font-extrabold uppercase tracking-[0.08em] text-bull-400 hover:bg-bull-500/15 disabled:opacity-35"
        >
          <Play className="h-3.5 w-3.5" /> Arm engine
        </button>
        <button
          onClick={() => stopMutation.mutate()}
          disabled={!isRunning || stopMutation.isPending}
          className="flex h-8 items-center justify-center gap-1.5 rounded-md border border-ink-700 bg-ink-800 text-[9px] font-extrabold uppercase tracking-[0.08em] text-fg-400 hover:text-fg-200 disabled:opacity-35"
        >
          <Square className="h-3.5 w-3.5" /> Disarm
        </button>
      </div>
    </section>
  )
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="min-w-0 rounded border border-ink-800/80 px-2 py-1.5">
      <div className="text-[7px] font-bold uppercase tracking-[0.11em] text-fg-600">{label}</div>
      <div className={clsx('mt-0.5 truncate font-semibold text-fg-300', accent && 'tnum text-gold-300')}>{value}</div>
    </div>
  )
}

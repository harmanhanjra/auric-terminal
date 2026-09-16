import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { clsx } from 'clsx'
import { Play, Square, BrainCircuit } from 'lucide-react'
import { api, ApiError } from '../lib/api'

export function EngineCard({ activeSymbol = 'XAUUSD' }: { activeSymbol?: string }) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['engine'] })
    queryClient.invalidateQueries({ queryKey: ['symbols'] })
  }

  const onError = (e: unknown) => {
    setActionError(e instanceof ApiError ? `Engine: ${e.message}` : 'Engine request failed')
  }

  const startMutation = useMutation({
    mutationFn: () => api.symbolStart(activeSymbol),
    onSuccess: () => {
      setActionError(null)
      invalidate()
    },
    onError,
  })

  const stopMutation = useMutation({
    mutationFn: () => api.symbolStop(activeSymbol),
    onSuccess: () => {
      setActionError(null)
      invalidate()
    },
    onError,
  })

  const { data: engineData } = useQuery({
    queryKey: ['engine'],
    queryFn: api.engine,
    refetchInterval: 2500,
  })

  const { data: kronosStatus } = useQuery({
    queryKey: ['kronos-status'],
    queryFn: api.kronosStatus,
    staleTime: 30_000,
  })

  const isRunning = engineData?.running ?? false
  const strategyName = (engineData?.strategy || 'ema144_pullback').replace(/_/g, ' ')
  const timeframe = engineData?.timeframe || 'M15'
  const trades = engineData?.trades ?? 0

  return (
    <div className="flex flex-col gap-2.5 p-3 bg-ink-900/60">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-gold-400 animate-pulse" />
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-fg-300">
            {activeSymbol} Algo Engine
          </span>
        </div>
        <span
          className={clsx(
            'rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase',
            isRunning ? 'bg-bull-500/20 text-bull-400' : 'bg-bear-500/20 text-bear-400',
          )}
        >
          {isRunning ? 'RUNNING' : 'STOPPED'}
        </span>
      </div>

      <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-2.5 space-y-1.5">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-fg-500">Active Strategy:</span>
          <span className="font-semibold text-fg-100 uppercase text-[10px]">{strategyName}</span>
        </div>

        <div className="flex items-center justify-between text-[11px]">
          <span className="text-fg-500">Base Timeframe:</span>
          <span className="font-mono font-semibold text-gold-400">{timeframe}</span>
        </div>

        <div className="flex items-center justify-between text-[11px]">
          <span className="text-fg-500">Signal State:</span>
          <span
            className={clsx(
              'font-semibold uppercase text-[10px]',
              engineData?.signal?.side === 1
                ? 'text-bull-400'
                : engineData?.signal?.side === -1
                  ? 'text-bear-400'
                  : 'text-fg-400',
            )}
          >
            {engineData?.signal?.side === 1 ? 'BUY' : engineData?.signal?.side === -1 ? 'SELL' : 'SCANNING'}
          </span>
        </div>

        <div className="flex items-center justify-between text-[11px]">
          <span className="text-fg-500">Execution Count:</span>
          <span className="font-mono text-fg-200">{trades} trades</span>
        </div>
      </div>

      {/* Kronos AI status strip */}
      <div className="flex items-center justify-between rounded-md border border-ink-700/60 bg-ink-800/40 px-2 py-1.5 text-[10px]">
        <div className="flex items-center gap-1.5 text-fg-400">
          <BrainCircuit className="h-3.5 w-3.5 text-gold-400" />
          <span>Kronos AI Model</span>
        </div>
        <span className="font-medium text-bull-400">
          {kronosStatus?.ok ? 'Active · 1.25M param' : 'Ready · Local Data'}
        </span>
      </div>

      {/* Action buttons */}
      {actionError && (
        <div className="rounded-md border border-bear-500/30 bg-bear-500/10 px-2 py-1.5 text-[10px] text-bear-400">
          {actionError}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 pt-1">
        <button
          onClick={() => startMutation.mutate()}
          disabled={isRunning || startMutation.isPending}
          className="flex items-center justify-center gap-1.5 rounded-md bg-bull-500/20 border border-bull-500/40 py-1.5 text-[10px] font-bold uppercase text-bull-300 hover:bg-bull-500/30 disabled:opacity-40 transition-colors"
        >
          <Play className="h-3 w-3 fill-current" />
          <span>Start Loop</span>
        </button>

        <button
          onClick={() => stopMutation.mutate()}
          disabled={!isRunning || stopMutation.isPending}
          className="flex items-center justify-center gap-1.5 rounded-md bg-bear-500/20 border border-bear-500/40 py-1.5 text-[10px] font-bold uppercase text-bear-300 hover:bg-bear-500/30 disabled:opacity-40 transition-colors"
        >
          <Square className="h-3 w-3 fill-current" />
          <span>Stop Loop</span>
        </button>
      </div>
    </div>
  )
}

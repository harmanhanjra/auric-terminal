import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Activity,
  DatabaseBackup,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  Siren,
  CloudDownload,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { api, ApiError, getAuthKey, setAuthKey } from '../lib/api'
import type { ExecutionStage } from '../lib/types'

const STAGES: ExecutionStage[] = ['shadow', 'paper', 'assisted', 'auto']

export function ProductionOpsCard() {
  const queryClient = useQueryClient()
  const [credential, setCredential] = useState(() => getAuthKey())
  const [message, setMessage] = useState<string | null>(null)

  const { data: readiness } = useQuery({
    queryKey: ['readiness'],
    queryFn: api.readiness,
    refetchInterval: 5000,
    retry: false,
  })

  const { data: status, error: statusError } = useQuery({
    queryKey: ['system-status', credential],
    queryFn: api.systemStatus,
    refetchInterval: 5000,
    retry: false,
  })

  const { data: news } = useQuery({
    queryKey: ['news-events', credential],
    queryFn: api.newsEvents,
    refetchInterval: 15_000,
    retry: false,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['readiness'] })
    queryClient.invalidateQueries({ queryKey: ['system-status'] })
    queryClient.invalidateQueries({ queryKey: ['engine'] })
    queryClient.invalidateQueries({ queryKey: ['symbols'] })
  }

  const stageMutation = useMutation({
    mutationFn: (stage: ExecutionStage) => api.setExecutionStage(stage),
    onSuccess: (result) => {
      setMessage(`Execution stage → ${result.executionStage.toUpperCase()}`)
      invalidate()
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Stage change failed'),
  })

  const resumeMutation = useMutation({
    mutationFn: api.resumeSystem,
    onSuccess: () => {
      setMessage('Global circuit resumed')
      invalidate()
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Resume failed'),
  })

  const reconcileMutation = useMutation({
    mutationFn: api.reconcile,
    onSuccess: () => {
      setMessage('Broker reconciliation completed')
      invalidate()
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Reconciliation failed'),
  })

  const backupMutation = useMutation({
    mutationFn: api.backupNow,
    onSuccess: (result) => setMessage(`Backup created: ${result.file}`),
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Backup failed'),
  })

  const newsSyncMutation = useMutation({
    mutationFn: api.syncNews,
    onSuccess: (result) => {
      setMessage(result.configured ? `Calendar sync: ${result.ingested} event(s)` : 'No normalized news feed configured')
      queryClient.invalidateQueries({ queryKey: ['news-events'] })
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : 'Calendar sync failed'),
  })

  const production = status ?? readiness?.production
  const stage = production?.executionStage ?? 'paper'
  const halted = production?.circuit?.halted ?? false
  const now = Date.now()
  const activeNews = (news?.events ?? []).filter(
    (event) => Boolean(event.enabled) && event.start_ms <= now && event.end_ms >= now,
  )
  const authRequired = readiness?.production?.authRequired ?? production?.authRequired ?? false
  const authError = statusError instanceof ApiError && statusError.status === 401

  const saveCredential = () => {
    setAuthKey(credential.trim())
    setMessage(credential.trim() ? 'Access credential applied to this session' : 'Access credential cleared')
    invalidate()
  }

  return (
    <section className="border-b border-ink-700/70 bg-ink-900/55 p-3">
      <div className="mb-2.5 flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[10px] font-extrabold uppercase tracking-[0.12em] text-fg-300">
            <ShieldCheck className="h-3.5 w-3.5 text-gold-300" />
            Production Control
          </div>
          <div className="mt-0.5 text-[8px] uppercase tracking-[0.1em] text-fg-600">
            V3 · RBAC · policy · reconciliation
          </div>
        </div>
        <span
          className={clsx(
            'rounded border px-2 py-1 text-[8px] font-black uppercase tracking-[0.1em]',
            readiness?.ready
              ? 'border-bull-500/30 bg-bull-500/10 text-bull-400'
              : 'border-gold-600/35 bg-gold-600/10 text-gold-300',
          )}
        >
          {readiness?.ready ? 'READY' : 'CHECKS'}
        </span>
      </div>

      <div className="rounded-lg border border-ink-700/80 bg-ink-950/55 p-2.5">
        <div className="mb-1 text-[8px] font-bold uppercase tracking-[0.12em] text-fg-600">
          Operator access
        </div>
        <div className="flex gap-1.5">
          <div className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-2 focus-within:border-gold-600/60">
            <KeyRound className="h-3.5 w-3.5 shrink-0 text-fg-500" />
            <input
              type="password"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              placeholder={authRequired ? 'RBAC access key required' : 'Local mode · optional key'}
              autoComplete="off"
              className="min-w-0 flex-1 bg-transparent text-[10px] text-fg-200 outline-none placeholder:text-fg-600"
              aria-label="Auric RBAC access key"
            />
          </div>
          <button
            onClick={saveCredential}
            className="rounded-md border border-ink-700 bg-ink-800 px-2 text-[8px] font-extrabold uppercase tracking-[0.08em] text-fg-300 hover:bg-ink-700"
          >
            Apply
          </button>
        </div>
        {authError ? (
          <div className="mt-1.5 text-[8px] text-bear-400">Authentication required or access key is not valid.</div>
        ) : null}
      </div>

      <div className="mt-2 rounded-lg border border-ink-700/80 bg-ink-950/55 p-2.5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[8px] font-bold uppercase tracking-[0.12em] text-fg-600">Execution promotion</span>
          <span className="text-[9px] font-extrabold uppercase text-gold-300">{stage}</span>
        </div>
        <div className="grid grid-cols-4 gap-1">
          {STAGES.map((item) => (
            <button
              key={item}
              onClick={() => stageMutation.mutate(item)}
              disabled={stageMutation.isPending}
              className={clsx(
                'rounded border px-1 py-1.5 text-[7px] font-extrabold uppercase tracking-[0.07em] transition',
                item === stage
                  ? 'border-gold-600/50 bg-gold-600/15 text-gold-300'
                  : 'border-ink-700 bg-ink-800 text-fg-500 hover:text-fg-300',
              )}
            >
              {item}
            </button>
          ))}
        </div>
        <div className="mt-2 text-[8px] leading-4 text-fg-600">
          Shadow = signals only · Paper = simulated fills · Assisted = manual live · Auto = autonomous live.
        </div>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5">
        <StatusTile
          label="Circuit"
          value={halted ? 'HALTED' : 'NORMAL'}
          tone={halted ? 'bear' : 'bull'}
          icon={halted ? <ShieldOff className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
        />
        <StatusTile
          label="News guard"
          value={activeNews.length ? `${activeNews.length} ACTIVE` : production?.newsGuard?.enabled ? 'ARMED' : 'OFF'}
          tone={activeNews.length ? 'bear' : 'neutral'}
          icon={<Siren className="h-3 w-3" />}
        />
      </div>

      <div className="mt-2 rounded-md border border-ink-700/70 bg-ink-800/40 p-2">
        <div className="mb-1.5 flex items-center justify-between text-[8px]">
          <span className="font-bold uppercase tracking-[0.1em] text-fg-600">Readiness checks</span>
          <Activity className="h-3 w-3 text-fg-500" />
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {Object.entries(readiness?.checks ?? {}).map(([name, ok]) => (
            <div key={name} className="flex items-center justify-between gap-2 text-[8px]">
              <span className="truncate text-fg-500">{name}</span>
              <span className={ok ? 'text-bull-400' : 'text-bear-400'}>{ok ? 'PASS' : 'FAIL'}</span>
            </div>
          ))}
        </div>
      </div>

      {activeNews.length ? (
        <div className="mt-2 rounded-md border border-bear-500/25 bg-bear-500/8 p-2">
          <div className="text-[8px] font-extrabold uppercase tracking-[0.1em] text-bear-400">Live blackout</div>
          <div className="mt-1 truncate text-[9px] text-fg-300">{activeNews[0]?.title}</div>
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-2 gap-1.5">
        <button
          onClick={() => reconcileMutation.mutate()}
          disabled={reconcileMutation.isPending}
          className="flex h-8 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-800 text-[8px] font-extrabold uppercase tracking-[0.08em] text-fg-300 hover:bg-ink-700 disabled:opacity-40"
        >
          <RefreshCw className={clsx('h-3 w-3', reconcileMutation.isPending && 'animate-spin')} />
          Reconcile
        </button>
        <button
          onClick={() => backupMutation.mutate()}
          disabled={backupMutation.isPending}
          className="flex h-8 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-800 text-[8px] font-extrabold uppercase tracking-[0.08em] text-fg-300 hover:bg-ink-700 disabled:opacity-40"
        >
          <DatabaseBackup className="h-3 w-3" /> Backup
        </button>
        <button
          onClick={() => newsSyncMutation.mutate()}
          disabled={newsSyncMutation.isPending}
          className="flex h-8 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-800 text-[8px] font-extrabold uppercase tracking-[0.08em] text-fg-300 hover:bg-ink-700 disabled:opacity-40"
        >
          <CloudDownload className="h-3 w-3" /> Sync calendar
        </button>
        <button
          onClick={() => resumeMutation.mutate()}
          disabled={!halted || resumeMutation.isPending}
          className="h-8 rounded-md border border-bull-500/25 bg-bull-500/8 text-[8px] font-extrabold uppercase tracking-[0.08em] text-bull-400 hover:bg-bull-500/15 disabled:opacity-30"
        >
          Resume circuit
        </button>
      </div>

      {message ? (
        <div className="mt-2 rounded border border-ink-700 bg-ink-950/70 px-2 py-1.5 text-[8px] text-fg-400" aria-live="polite">
          {message}
        </div>
      ) : null}
    </section>
  )
}

function StatusTile({
  label,
  value,
  tone,
  icon,
}: {
  label: string
  value: string
  tone: 'bull' | 'bear' | 'neutral'
  icon: ReactNode
}) {
  return (
    <div className="rounded-md border border-ink-700/70 bg-ink-800/40 p-2">
      <div className="flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-600">
        {icon} {label}
      </div>
      <div
        className={clsx(
          'mt-1 text-[10px] font-extrabold',
          tone === 'bull' ? 'text-bull-400' : tone === 'bear' ? 'text-bear-400' : 'text-fg-300',
        )}
      >
        {value}
      </div>
    </div>
  )
}

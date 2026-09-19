import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RadioTower, ShieldCheck } from 'lucide-react'
import { clsx } from 'clsx'
import { api, setLiveKey, setSessionToken } from '../lib/api'

export function ProductionCard({ activeSymbol }: { activeSymbol: string }) {
  const { data: status } = useQuery({
    queryKey: ['production-status'],
    queryFn: api.productionStatus,
    refetchInterval: 5000,
  })
  const { data: readiness } = useQuery({
    queryKey: ['readiness'],
    queryFn: api.readiness,
    refetchInterval: 5000,
    retry: false,
  })

  const blackout = status?.blackout?.[activeSymbol]

  return (
    <section className="border-b border-ink-700/70 bg-ink-900/55 p-3">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={clsx(
            'grid h-7 w-7 place-items-center rounded-md border',
            readiness?.ready
              ? 'border-bull-500/30 bg-bull-500/10 text-bull-400'
              : 'border-bear-500/30 bg-bear-500/10 text-bear-400',
          )}>
            <ShieldCheck className="h-4 w-4" />
          </span>
          <div>
            <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-fg-300">Production Guard</div>
            <div className="text-[8px] uppercase tracking-[0.12em] text-fg-600">
              {status?.environment ?? 'loading'} · staged execution
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={clsx(
            'rounded border px-2 py-1 text-[8px] font-black uppercase tracking-[0.1em]',
            readiness?.ready
              ? 'border-bull-500/30 bg-bull-500/10 text-bull-400'
              : 'border-bear-500/30 bg-bear-500/10 text-bear-400',
          )}>
            {readiness?.ready ? 'READY' : 'BLOCKED'}
          </span>
          <button
            onClick={() => {
              setSessionToken('')
              setLiveKey('')
              window.location.reload()
            }}
            className="rounded border border-ink-700 px-2 py-1 text-[8px] font-bold uppercase tracking-[0.08em] text-fg-500 hover:text-fg-200"
            title="Clear operator session and live execution key"
          >
            Sign out
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-1.5 text-[9px]">
        <Metric label="Stage" value={status?.policy.stage?.toUpperCase() ?? '—'} />
        <Metric label="Auth" value={status?.authRequired ? (status.authConfigured ? 'ENFORCED' : 'MISCONFIG') : 'OPTIONAL'} />
        <Metric label="Reconciliation" value={status?.reconciliation.ok ? 'HEALTHY' : 'ATTENTION'} good={status?.reconciliation.ok} />
        <Metric label={activeSymbol + ' blackout'} value={blackout?.allowed === false ? 'ACTIVE' : 'CLEAR'} good={blackout?.allowed !== false} />
      </div>

      <div className="mt-2 rounded-md border border-ink-700/70 bg-ink-950/55 p-2">
        <div className="mb-1.5 flex items-center gap-1 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">
          <RadioTower className="h-3 w-3" /> Broker integrity
        </div>
        <div className="flex items-center justify-between text-[9px] text-fg-400">
          <span>Open / pending</span>
          <span className="tnum text-fg-200">
            {status ? status.reconciliation.positionCount + ' / ' + status.reconciliation.pendingCount : '—'}
          </span>
        </div>
        <div className="mt-1 flex items-center justify-between text-[9px] text-fg-400">
          <span>Unmatched tickets</span>
          <span className={clsx('tnum', status?.reconciliation.unmatchedTickets.length ? 'text-bear-400' : 'text-bull-400')}>
            {status?.reconciliation.unmatchedTickets.length ?? 0}
          </span>
        </div>
      </div>

      {readiness?.checks?.some((c) => !c.ok) ? (
        <div className="mt-2 space-y-1">
          {readiness.checks.filter((c) => !c.ok).slice(0, 3).map((check) => (
            <div key={check.name} className="flex items-start gap-1.5 rounded border border-bear-500/20 bg-bear-500/5 px-2 py-1.5">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-bear-400" />
              <span className="text-[8px] leading-relaxed text-fg-400">{check.detail}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-2 flex items-center gap-1.5 text-[8px] text-bull-400">
          <CheckCircle2 className="h-3 w-3" /> All configured production gates are healthy.
        </div>
      )}
    </section>
  )
}

function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded border border-ink-800/80 px-2 py-1.5">
      <div className="text-[7px] font-bold uppercase tracking-[0.11em] text-fg-600">{label}</div>
      <div className={clsx(
        'mt-0.5 truncate font-semibold',
        good === true ? 'text-bull-400' : good === false ? 'text-bear-400' : 'text-fg-300',
      )}>{value}</div>
    </div>
  )
}
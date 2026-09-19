import { useQuery } from '@tanstack/react-query'
import { Bell, ShieldAlert, Terminal } from 'lucide-react'
import { api } from '../lib/api'
import { Modal } from './Modal'

export function AlertsModal() {
  const { data: engine } = useQuery({
    queryKey: ['engine-alerts'],
    queryFn: api.engine,
    refetchInterval: 2500,
  })

  const entries = (engine?.log ?? []).slice(0, 10)

  return (
    <Modal id="alerts" title="Event Center" subtitle="Live engine, execution and risk events">
      <div className="flex max-h-[560px] flex-col gap-2 overflow-auto p-4">
        {engine?.risk?.halted ? (
          <div className="flex items-start gap-3 rounded-lg border border-bear-500/35 bg-bear-500/10 p-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 text-bear-400" />
            <div>
              <div className="text-[9px] font-extrabold uppercase tracking-[0.12em] text-bear-400">Risk circuit breaker</div>
              <p className="mt-1 text-[11px] text-fg-300">Trading is halted. Reset the risk gate only after reviewing the cause.</p>
            </div>
          </div>
        ) : null}

        {entries.length === 0 ? (
          <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-ink-700 text-fg-500">
            <Bell className="h-5 w-5" />
            <span className="text-[11px]">No engine events yet.</span>
          </div>
        ) : (
          entries.map((event, i) => (
            <div key={`${String(event.ts)}-${i}`} className="flex items-start gap-3 rounded-lg border border-ink-700 bg-ink-800/70 p-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-ink-700 bg-ink-950 text-gold-300">
                <Terminal className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[9px] font-extrabold uppercase tracking-[0.12em] text-fg-400">{event.type || 'ENGINE'}</div>
                  <div className="tnum text-[8px] text-fg-600">
                    {typeof event.ts === 'number' ? new Date(event.ts).toLocaleTimeString() : ''}
                  </div>
                </div>
                <p className="mt-1 break-words text-[11px] text-fg-300">
                  {event.reason || (event.reasons ? event.reasons.join(' · ') : 'Engine lifecycle event')}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </Modal>
  )
}

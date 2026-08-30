import { Bell, ShieldAlert } from 'lucide-react'
import { Modal } from './Modal'

const ALERTS = [
  {
    icon: Bell,
    type: 'PRICE ALERT',
    color: 'text-gold-400',
    bg: 'bg-gold-600/10',
    ring: 'ring-gold-600/30',
    body: 'XAU/USD above 5,030.00 — triggered at 10:42',
  },
  {
    icon: ShieldAlert,
    type: 'SIGNAL ALERT',
    color: 'text-bear-400',
    bg: 'bg-bear-500/10',
    ring: 'ring-bear-500/30',
    body: 'EMA 144 Pullback — LONG signal on M15 · Confirm 3/3',
  },
]

export function AlertsModal() {
  return (
    <Modal id="alerts" title="Alerts" subtitle="Active price and signal notifications">
      <div className="flex flex-col gap-2 p-4">
        {ALERTS.map((a, i) => (
          <div key={i} className="flex items-start gap-3 rounded-lg border border-ink-700 bg-ink-800 p-3">
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${a.bg} ${a.color} ring-1 ${a.ring}`}>
              <a.icon className="h-4 w-4" />
            </span>
            <div>
              <div className={`text-[9px] font-bold uppercase tracking-[0.12em] ${a.color}`}>{a.type}</div>
              <p className="mt-1 text-[12px] text-fg-200">{a.body}</p>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
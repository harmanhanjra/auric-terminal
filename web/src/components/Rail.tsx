import { clsx } from 'clsx'
import {
  CandlestickChart,
  Gauge,
  History,
  LayoutGrid,
  Settings,
  ShieldAlert,
  Target,
  ChartLine,
  BrainCircuit,
} from 'lucide-react'
import type { ViewKey } from '../App'

interface RailProps {
  view: ViewKey
  onNavigate: (key: ViewKey) => void
}

const ITEMS: { key: ViewKey; label: string; icon: typeof Target }[] = [
  { key: 'chart', label: 'Chart', icon: CandlestickChart },
  { key: 'strategies', label: 'Strategies', icon: LayoutGrid },
  { key: 'backtest', label: 'Backtest', icon: ChartLine },
  { key: 'kronos', label: 'Kronos AI', icon: BrainCircuit },
  { key: 'positions', label: 'Positions', icon: Target },
  { key: 'risk', label: 'Risk', icon: ShieldAlert },
  { key: 'journal', label: 'Journal', icon: History },
  { key: 'alerts', label: 'Alerts', icon: Gauge },
]

export function Rail({ view, onNavigate }: RailProps) {
  return (
    <nav className="flex flex-col items-center gap-1 border-r border-ink-700/70 bg-ink-900 py-3">
      {ITEMS.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          title={label}
          aria-label={label}
          onClick={() => onNavigate(key)}
          className={clsx(
            'relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors',
            view === key
              ? 'text-gold-400'
              : 'text-fg-500 hover:bg-ink-800 hover:text-fg-200',
          )}
        >
          {view === key && (
            <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-gold-400" />
          )}
          <Icon className="h-5 w-5" strokeWidth={1.7} />
        </button>
      ))}
      <div className="mt-auto flex flex-col gap-1">
        <button
          title="Settings"
          aria-label="Settings"
          onClick={() => alert('Settings coming soon')}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-fg-500 transition-colors hover:bg-ink-800 hover:text-fg-200"
        >
          <Settings className="h-5 w-5" strokeWidth={1.7} />
        </button>
      </div>
    </nav>
  )
}
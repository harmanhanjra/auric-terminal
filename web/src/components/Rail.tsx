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
    <nav className="relative flex w-16 flex-col items-center gap-1 border-r border-white/[0.055] bg-ink-900/74 py-3 backdrop-blur-xl">
      {ITEMS.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          title={label}
          aria-label={label}
          onClick={() => onNavigate(key)}
          data-active={view === key}
          className={clsx(
            'group/nav auric-rail-item relative flex h-11 w-11 items-center justify-center rounded-xl transition-[background-color,color,transform] duration-200',
            view === key
              ? 'bg-gold-400/[0.065] text-gold-300'
              : 'text-fg-500 hover:bg-white/[0.045] hover:text-fg-100',
          )}
        >
          {view === key && (
            <span className="absolute -left-[11px] top-1/2 h-6 w-[2px] -translate-y-1/2 rounded-r bg-gold-300 shadow-[0_0_14px_rgba(222,190,90,.6)]" />
          )}
          <Icon className="relative z-10 h-[18px] w-[18px]" strokeWidth={1.75} />
          <span className="pointer-events-none absolute left-[52px] z-50 whitespace-nowrap rounded-md border border-white/[0.07] bg-ink-900/95 px-2 py-1 text-[9px] font-semibold tracking-wide text-fg-200 opacity-0 shadow-2xl backdrop-blur-xl transition-all duration-150 group-hover/nav:translate-x-1 group-hover/nav:opacity-100">
            {label}
          </span>
        </button>
      ))}
      <div className="mt-auto flex flex-col gap-1">
        <button
          title="Settings"
          aria-label="Settings"
          onClick={() => alert('Settings coming soon')}
          className="auric-rail-item flex h-11 w-11 items-center justify-center rounded-xl text-fg-500 transition-colors hover:bg-white/[0.045] hover:text-fg-100"
        >
          <Settings className="h-5 w-5" strokeWidth={1.7} />
        </button>
      </div>
    </nav>
  )
}
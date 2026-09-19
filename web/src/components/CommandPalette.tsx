import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BrainCircuit,
  CandlestickChart,
  ChartLine,
  Command,
  Gauge,
  History,
  LayoutGrid,
  Search,
  ShieldAlert,
  Target,
  X,
} from 'lucide-react'
import type { ViewKey } from '../App'
import { clsx } from 'clsx'

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onNavigate: (key: ViewKey) => void
  activeSymbol: string
  onSelectSymbol: (symbol: string) => void
  onApplyLayout: (layout: 'execution' | 'research' | 'compact') => void
}

type CommandItem = {
  id: string
  label: string
  hint: string
  keywords: string
  icon: typeof Search
  run: () => void
}

export function CommandPalette({
  open,
  onOpenChange,
  onNavigate,
  activeSymbol,
  onSelectSymbol,
  onApplyLayout,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        onOpenChange(!open)
      }
      if (event.key === 'Escape' && open) onOpenChange(false)
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onOpenChange, open])

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  const items = useMemo<CommandItem[]>(() => {
    const nav = (id: ViewKey, label: string, hint: string, icon: typeof Search): CommandItem => ({
      id: `nav-${id}`,
      label,
      hint,
      keywords: `${label} ${id}`,
      icon,
      run: () => onNavigate(id),
    })

    return [
      nav('chart', 'Open chart workspace', 'Market view', CandlestickChart),
      nav('strategies', 'Open strategy matrix', 'Algorithms', LayoutGrid),
      nav('backtest', 'Open backtest lab', 'Research', ChartLine),
      nav('kronos', 'Open Kronos AI', 'Forecast copilot', BrainCircuit),
      nav('positions', 'Open positions', 'Exposure', Target),
      nav('risk', 'Open risk radar', 'Guardrails', ShieldAlert),
      nav('journal', 'Open trade journal', 'History', History),
      nav('alerts', 'Open alerts', 'Monitoring', Gauge),
      ...['XAUUSD', 'BTCUSD', 'EURUSD'].map((symbol) => ({
        id: `symbol-${symbol}`,
        label: `Switch to ${symbol}`,
        hint: symbol === activeSymbol ? 'Active symbol' : 'Instrument',
        keywords: `symbol instrument ${symbol}`,
        icon: CandlestickChart,
        run: () => onSelectSymbol(symbol),
      })),
      {
        id: 'layout-execution',
        label: 'Layout · Execution',
        hint: 'Wide order rail',
        keywords: 'layout execution trading',
        icon: Command,
        run: () => onApplyLayout('execution'),
      },
      {
        id: 'layout-research',
        label: 'Layout · Research',
        hint: 'Large dock',
        keywords: 'layout research backtest',
        icon: Command,
        run: () => onApplyLayout('research'),
      },
      {
        id: 'layout-compact',
        label: 'Layout · Compact',
        hint: 'Maximum chart',
        keywords: 'layout compact chart',
        icon: Command,
        run: () => onApplyLayout('compact'),
      },
    ]
  }, [activeSymbol, onApplyLayout, onNavigate, onSelectSymbol])

  const filtered = query.trim()
    ? items.filter((item) =>
        `${item.label} ${item.hint} ${item.keywords}`.toLowerCase().includes(query.toLowerCase()),
      )
    : items

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/58 px-4 pt-[12vh] backdrop-blur-md"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onOpenChange(false)
      }}
    >
      <div
        className="auric-surface auric-surface-elevated w-full max-w-[680px] overflow-hidden rounded-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Auric command center"
      >
        <div className="flex h-14 items-center gap-3 border-b border-white/[0.065] px-4">
          <Search className="h-4 w-4 text-gold-300" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search modules, symbols, layouts…"
            className="h-full min-w-0 flex-1 bg-transparent text-sm text-fg-100 outline-none placeholder:text-fg-600"
          />
          <span className="rounded border border-white/[0.07] bg-white/[0.035] px-2 py-1 text-[9px] font-bold text-fg-500">
            ESC
          </span>
          <button
            onClick={() => onOpenChange(false)}
            className="grid h-8 w-8 place-items-center rounded-lg text-fg-500 hover:bg-white/[0.05] hover:text-fg-100"
            aria-label="Close command center"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[430px] overflow-y-auto p-2">
          {filtered.length ? (
            filtered.map((item) => {
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    item.run()
                    onOpenChange(false)
                  }}
                  className={clsx(
                    'group flex w-full items-center gap-3 rounded-xl border border-transparent px-3 py-2.5 text-left',
                    'hover:border-white/[0.06] hover:bg-white/[0.045]',
                  )}
                >
                  <span className="grid h-8 w-8 place-items-center rounded-lg border border-white/[0.06] bg-white/[0.025] text-fg-500 group-hover:text-gold-300">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-semibold text-fg-200 group-hover:text-fg-100">
                      {item.label}
                    </span>
                    <span className="mt-0.5 block text-[9px] uppercase tracking-[0.1em] text-fg-600">
                      {item.hint}
                    </span>
                  </span>
                </button>
              )
            })
          ) : (
            <div className="px-4 py-10 text-center text-[11px] text-fg-500">No commands found.</div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-white/[0.055] px-4 py-2 text-[9px] text-fg-600">
          <span>Navigate Auric without leaving the keyboard</span>
          <span>Ctrl / ⌘ + K</span>
        </div>
      </div>
    </div>
  )
}

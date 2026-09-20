import { useEffect, useMemo, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { clsx } from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { BrainCircuit, LayoutPanelTop, PanelBottomClose, PanelRightClose, Search } from 'lucide-react'
import { TopBar } from './components/TopBar'
import { Rail } from './components/Rail'
import { ChartPanel } from './components/ChartPanel'
import { OrderTicket } from './components/OrderTicket'
import { DepthPanel } from './components/DepthPanel'
import { EngineCard } from './components/EngineCard'
import { ProductionCard } from './components/ProductionCard'
import { Dock } from './components/Dock'
import { StrategyModal } from './components/StrategyModal'
import { BacktestModal } from './components/BacktestModal'
import { AlertsModal } from './components/AlertsModal'
import { KronosModal } from './components/KronosModal'
import { CommandPalette } from './components/CommandPalette'
import { openModal } from './components/modalController'
import { AuricBackdrop } from './components/effects/AuricBackdrop'
import { useMarketFeed } from './lib/useMarketFeed'
import { api } from './lib/api'
import type { Quote } from './lib/types'

export type ViewKey = 'chart' | 'strategies' | 'backtest' | 'positions' | 'risk' | 'journal' | 'alerts' | 'kronos'
type LayoutPreset = 'execution' | 'research' | 'compact'
type InspectorTab = 'trade' | 'book' | 'engine' | 'ops'

const INSPECTOR_TABS: { key: InspectorTab; label: string }[] = [
  { key: 'trade', label: 'Trade' },
  { key: 'book', label: 'Book' },
  { key: 'engine', label: 'Engine' },
  { key: 'ops', label: 'Ops' },
]

interface WorkspaceLayout {
  sideWidth: number
  dockHeight: number
  sideVisible: boolean
  dockVisible: boolean
}

const LAYOUTS: Record<LayoutPreset, WorkspaceLayout> = {
  execution: { sideWidth: 392, dockHeight: 280, sideVisible: true, dockVisible: true },
  research: { sideWidth: 330, dockHeight: 360, sideVisible: true, dockVisible: true },
  compact: { sideWidth: 340, dockHeight: 220, sideVisible: false, dockVisible: true },
}

function loadWorkspaceLayout(): WorkspaceLayout {
  try {
    const raw = localStorage.getItem('auric.workspaceLayout')
    if (!raw) return LAYOUTS.execution
    const parsed = JSON.parse(raw) as Partial<WorkspaceLayout>
    return {
      sideWidth: Math.min(520, Math.max(320, parsed.sideWidth ?? LAYOUTS.execution.sideWidth)),
      dockHeight: Math.min(460, Math.max(180, parsed.dockHeight ?? LAYOUTS.execution.dockHeight)),
      sideVisible: parsed.sideVisible ?? true,
      dockVisible: parsed.dockVisible ?? true,
    }
  } catch {
    return LAYOUTS.execution
  }
}

export default function App() {
  const [view, setView] = useState<ViewKey>('chart')
  const [live, setLive] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [inspector, setInspector] = useState<InspectorTab>('trade')
  const [layout, setLayout] = useState<WorkspaceLayout>(loadWorkspaceLayout)
  const [activeSymbol, setActiveSymbol] = useState(() => {
    try {
      return localStorage.getItem('auric.activeSymbol') || 'XAUUSD'
    } catch {
      return 'XAUUSD'
    }
  })
  const { ticks, status } = useMarketFeed()

  const { data: symbolSeed } = useQuery({
    queryKey: ['symbol-quote', activeSymbol],
    queryFn: () => api.symbolQuote(activeSymbol),
    refetchInterval: 5000,
    staleTime: 2000,
    retry: false,
  })

  const quote: Quote = useMemo(() => {
    const liveQuote = ticks[activeSymbol] ?? symbolSeed ?? undefined
    if (liveQuote && liveQuote.price > 0 && Date.now() - liveQuote.timestamp < 15000) return liveQuote
    return {
      symbol: activeSymbol,
      bid: 0,
      ask: 0,
      price: 0,
      spread: 0,
      source: status === 'connecting' ? 'Connecting to MT5' : 'MT5 unavailable',
      timestamp: 0,
    }
  }, [ticks, symbolSeed, activeSymbol, status])

  useEffect(() => {
    try {
      localStorage.setItem('auric.activeSymbol', activeSymbol)
    } catch {
      /* storage unavailable */
    }
  }, [activeSymbol])

  useEffect(() => {
    try {
      localStorage.setItem('auric.workspaceLayout', JSON.stringify(layout))
    } catch {
      /* storage unavailable */
    }
  }, [layout])

  const openModule = (key: string) => {
    const next = key as ViewKey
    setView(next)
    if (next === 'strategies' || next === 'backtest' || next === 'alerts' || next === 'kronos') {
      openModal(next)
    }
  }

  const applyLayout = (preset: LayoutPreset) => setLayout(LAYOUTS[preset])

  const beginSideResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = layout.sideWidth

    const move = (moveEvent: PointerEvent) => {
      const next = Math.min(520, Math.max(320, startWidth - (moveEvent.clientX - startX)))
      setLayout((current) => ({ ...current, sideWidth: next }))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const beginDockResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = layout.dockHeight

    const move = (moveEvent: PointerEvent) => {
      const next = Math.min(460, Math.max(180, startHeight - (moveEvent.clientY - startY)))
      setLayout((current) => ({ ...current, dockHeight: next }))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const gridTemplate = layout.sideVisible
    ? `64px minmax(0,1fr) 5px ${layout.sideWidth}px`
    : '64px minmax(0,1fr)'

  return (
    <div className="auric-shell relative h-screen overflow-hidden bg-ink-950 text-fg-200 selection:bg-gold-400/20">
      <AuricBackdrop />
      <div className="relative z-10 flex h-screen flex-col overflow-hidden">
        <TopBar
          quote={quote}
          live={live}
          onToggleLive={setLive}
          feedStatus={status}
          activeSymbol={activeSymbol}
          onSelectSymbol={setActiveSymbol}
          onOpenCommand={() => setCommandOpen(true)}
        />

        <div
          className="terminal-workspace grid min-h-0 flex-1 overflow-hidden"
          style={{ gridTemplateColumns: gridTemplate }}
        >
          <Rail view={view} onNavigate={openModule} />

          <main className="relative flex min-h-0 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-hidden">
              <ChartPanel quote={quote} activeSymbol={activeSymbol} onSelectSymbol={setActiveSymbol} />
            </div>

            {layout.dockVisible ? (
              <>
                <div
                  className="auric-resize-handle auric-resize-horizontal h-[5px] shrink-0"
                  onPointerDown={beginDockResize}
                  role="separator"
                  aria-orientation="horizontal"
                  aria-label="Resize lower trading dock"
                />
                <div
                  className="shrink-0 overflow-hidden border-t border-white/[0.06] bg-ink-900/60"
                  style={{ height: layout.dockHeight }}
                >
                  <Dock quote={quote} live={live} view={view} onNavigate={openModule} />
                </div>
              </>
            ) : null}

            <div
              className="absolute right-3 z-30 flex items-center gap-1.5"
              style={{ bottom: layout.dockVisible ? layout.dockHeight + 14 : 12 }}
            >
              <button
                onClick={() => setCommandOpen(true)}
                className="auric-float-control"
                title="Command center · Ctrl/⌘ + K"
              >
                <Search className="h-3.5 w-3.5" />
                <span>Command</span>
              </button>
              <button
                onClick={() => openModule('kronos')}
                className="auric-float-control auric-float-control-premium"
                title="Open Kronos AI forecast copilot"
              >
                <BrainCircuit className="h-3.5 w-3.5" />
                <span>Kronos</span>
              </button>
            </div>

            <div
              className="absolute bottom-3 left-3 z-30 flex items-center gap-1 rounded-lg border border-white/[0.055] bg-ink-950/78 p-1 shadow-lg backdrop-blur-xl"
            >
              <button
                className="auric-layout-button"
                onClick={() => applyLayout('execution')}
                title="Execution layout"
              >
                <LayoutPanelTop className="h-3.5 w-3.5" />
              </button>
              <button
                className="auric-layout-button"
                onClick={() => setLayout((current) => ({ ...current, dockVisible: !current.dockVisible }))}
                title="Toggle lower dock"
              >
                <PanelBottomClose className="h-3.5 w-3.5" />
              </button>
              <button
                className="auric-layout-button"
                onClick={() => setLayout((current) => ({ ...current, sideVisible: !current.sideVisible }))}
                title="Toggle execution sidebar"
              >
                <PanelRightClose className="h-3.5 w-3.5" />
              </button>
            </div>
          </main>

          {layout.sideVisible ? (
            <>
              <div
                className="auric-resize-handle auric-resize-vertical"
                onPointerDown={beginSideResize}
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize execution sidebar"
              />
              <aside className="auric-side-panel flex min-h-0 flex-col overflow-hidden">
                <div className="flex h-11 shrink-0 items-center gap-1 px-2">
                  {INSPECTOR_TABS.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setInspector(tab.key)}
                      data-active={inspector === tab.key}
                      className={clsx(
                        'auric-toolbar-button flex-1',
                        inspector === tab.key ? 'text-fg-100' : 'text-fg-500',
                      )}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className="min-h-0 flex-1 overflow-auto border-t border-white/[0.05]">
                  {inspector === 'trade' && (
                    <OrderTicket quote={quote} live={live} activeSymbol={activeSymbol} />
                  )}
                  {inspector === 'book' && <DepthPanel quote={quote} />}
                  {inspector === 'engine' && <EngineCard activeSymbol={activeSymbol} />}
                  {inspector === 'ops' && <ProductionCard activeSymbol={activeSymbol} />}
                </div>
              </aside>
            </>
          ) : null}
        </div>

        <StrategyModal />
        <BacktestModal />
        <AlertsModal />
        <KronosModal />
        <CommandPalette
          open={commandOpen}
          onOpenChange={setCommandOpen}
          onNavigate={openModule}
          activeSymbol={activeSymbol}
          onSelectSymbol={setActiveSymbol}
          onApplyLayout={applyLayout}
        />
      </div>
    </div>
  )
}

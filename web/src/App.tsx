import { useEffect, useMemo, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
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
    if (liveQuote && liveQuote.price > 0) return liveQuote
    return {
      symbol: activeSymbol,
      bid: 5024.36,
      ask: 5024.54,
      price: 5024.36,
      spread: 0.18,
      source: status === 'connecting' ? 'Connecting' : 'Demo',
      timestamp: Date.now(),
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

          <main className="relative flex min-h-0 flex-col overflow-hidden bg-ink-950/72 backdrop-blur-[2px]">
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
                  className="shrink-0 overflow-hidden bg-ink-900/72 backdrop-blur-xl"
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
              <aside className="auric-side-panel flex min-h-0 flex-col overflow-hidden bg-ink-900/72 backdrop-blur-xl">
                <div className="shrink-0 border-b border-white/[0.055]">
                  <OrderTicket quote={quote} live={live} activeSymbol={activeSymbol} />
                </div>
                <div className="min-h-0 flex-1 overflow-auto">
                  <ProductionCard activeSymbol={activeSymbol} />
                  <DepthPanel quote={quote} />
                  <EngineCard activeSymbol={activeSymbol} />
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

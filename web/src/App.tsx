import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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
import { openModal } from './components/Modal'
import { AuricBackdrop } from './components/effects/AuricBackdrop'
import { useMarketFeed } from './lib/useMarketFeed'
import { api } from './lib/api'
import type { Quote } from './lib/types'

export type ViewKey = 'chart' | 'strategies' | 'backtest' | 'positions' | 'risk' | 'journal' | 'alerts' | 'kronos'

export default function App() {
  const [view, setView] = useState<ViewKey>('chart')
  const [live, setLive] = useState(false)
  const [activeSymbol, setActiveSymbol] = useState(() => {
    try {
      return localStorage.getItem('auric.activeSymbol') || 'XAUUSD'
    } catch {
      return 'XAUUSD'
    }
  })
  const { ticks, status } = useMarketFeed()

  // REST seed for the active symbol (covers WS gaps + first paint).
  const { data: symbolSeed } = useQuery({
    queryKey: ['symbol-quote', activeSymbol],
    queryFn: () => api.symbolQuote(activeSymbol),
    refetchInterval: 5000,
    staleTime: 2000,
    retry: false,
  })

  const quote: Quote = useMemo(() => {
    const live = ticks[activeSymbol] ?? symbolSeed ?? undefined
    if (live && live.price > 0) return live
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
      /* ignore */
    }
  }, [activeSymbol])

  const openModule = (key: string) => {
    const k = key as ViewKey
    setView(k)
    if (k === 'strategies' || k === 'backtest' || k === 'alerts' || k === 'kronos') openModal(k)
  }

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
        />

        <div className="terminal-workspace grid min-h-0 flex-1 grid-cols-[64px_minmax(0,1fr)_392px] overflow-hidden">
          <Rail view={view} onNavigate={openModule} />

          <main className="flex min-h-0 flex-col overflow-hidden border-r border-white/[0.055] bg-ink-950/72 backdrop-blur-[2px]">
            <div className="min-h-0 flex-1 overflow-hidden">
              <ChartPanel quote={quote} activeSymbol={activeSymbol} onSelectSymbol={setActiveSymbol} />
            </div>
            <div className="h-[280px] shrink-0 overflow-hidden border-t border-white/[0.055] bg-ink-900/72 backdrop-blur-xl">
              <Dock quote={quote} live={live} view={view} onNavigate={openModule} />
            </div>
          </main>

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
        </div>

        <StrategyModal />
        <BacktestModal />
        <AlertsModal />
        <KronosModal />
      </div>
    </div>
  )
}

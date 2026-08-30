import { clsx } from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { Power, Save, Loader, RotateCcw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { fmtMoney, fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'
import { SymbolSelector } from './SymbolSelector'

interface TopBarProps {
  quote: Quote
  live: boolean
  onToggleLive: (live: boolean) => void
  feedStatus: string
  activeSymbol: string
  onSelectSymbol: (symbol: string) => void
}

const SESSIONS = [
  { name: 'SYDNEY', open: 22, close: 6 },
  { name: 'TOKYO', open: 0, close: 9 },
  { name: 'LONDON', open: 3, close: 12 },
  { name: 'NEW YORK', open: 8, close: 17 },
]

function getCurrentSession(): string {
  const hour = new Date().getUTCHours()
  for (const s of SESSIONS) {
    if (s.open <= s.close) {
      if (hour >= s.open && hour < s.close) return s.name
    } else if (hour >= s.open || hour < s.close) return s.name
  }
  return 'CLOSED'
}

export function TopBar({ quote, live, onToggleLive, feedStatus, activeSymbol, onSelectSymbol }: TopBarProps) {
  const { data: account } = useQuery({
    queryKey: ['account'],
    queryFn: api.account,
    refetchInterval: 10_000,
  })

  const session = getCurrentSession()
  const priceFlash = usePriceFlash(quote.price)

  return (
    <header className="flex h-14 shrink-0 items-center gap-0 border-b border-ink-700 bg-ink-900/80 backdrop-blur supports-[backdrop-filter]:bg-ink-900/70">
      {/* Brand */}
      <div className="flex h-full w-[200px] shrink-0 items-center gap-3 border-r border-ink-700 px-4">
        <div className="grid h-8 w-8 shrink-0 rotate-45 place-items-center rounded-lg border border-gold-600/50 bg-gradient-to-br from-ink-800 to-ink-900 shadow-[0_0_16px_rgba(201,162,39,0.18)]">
          <span className="h-2.5 w-2.5 rounded-[2px] bg-gold-400 shadow-[0_0_8px_rgba(201,162,39,0.9)]" />
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-bold tracking-[-0.02em] text-fg-100">
            Auric<span className="text-gold-400">Terminal</span>
          </div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.16em] text-fg-500">
            {activeSymbol} · Multi-Symbol
          </div>
        </div>
      </div>

      {/* Symbol picker — clickable, scrollable, drives header */}
      <SymbolSelector active={activeSymbol} onChange={onSelectSymbol} />

      {/* Quote */}
      <div className="flex h-full items-center gap-3 border-r border-ink-700 px-4">
        <div>
          <div className="text-[11px] font-bold text-fg-100">{activeSymbol}</div>
          <div className="text-[9px] text-fg-500">{quote.source || 'MT5'} · live</div>
        </div>
        <span className={clsx('tnum text-[22px] font-bold leading-none tracking-[-0.03em] text-fg-100', priceFlash === 'up' && 'animate-flash-up', priceFlash === 'down' && 'animate-flash-down')}>
          {fmtPrice(quote.price)}
        </span>
        <span className="tnum rounded-md border border-ink-700 bg-ink-800 px-2 py-1 text-[10px] font-medium text-fg-300">
          Spread {quote.spread.toFixed(2)}
        </span>
        <span className="hidden rounded-md border border-gold-600/30 bg-gold-600/10 px-2 py-1 text-[10px] font-bold tracking-wide text-gold-300 lg:block">
          {session}
        </span>
        <button
          onClick={() => onToggleLive(!live)}
          className={clsx('rounded-md border px-2.5 py-1 text-[10px] font-bold tracking-[0.08em] transition-colors', live ? 'border-bear-500/40 bg-bear-500/10 text-bear-500' : 'border-gold-600/40 bg-gold-600/10 text-gold-300')}
        >
          {live ? 'LIVE' : 'PAPER'}
        </button>
      </div>

      {/* Ticker — pure CSS marquee for reliability */}
      <div className="hidden flex-1 overflow-hidden lg:block">
        <div className="animate-[marquee_30s_linear_infinite] flex items-center gap-6 whitespace-nowrap text-[10px]">
          <TickerItem sym="XAUUSD" price={quote.price} />
          <TickerItem sym="XAGUSD" price={28.45} />
          <TickerItem sym="EURUSD" price={1.0875} />
          <TickerItem sym="GBPUSD" price={1.2654} />
          <TickerItem sym="USDJPY" price={149.85} />
          <TickerItem sym="USOIL" price={78.23} />
        </div>
      </div>

      {/* Account */}
      <div className="ml-auto hidden items-center gap-0 md:flex">
        <div className="flex flex-col items-end border-l border-ink-700 px-3">
          <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-fg-500">Balance</span>
          <span className="tnum text-[11px] font-semibold text-fg-100">{fmtMoney(account?.balance ?? 10000)}</span>
        </div>
        <div className="flex flex-col items-end border-l border-ink-700 px-3">
          <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-fg-500">Equity</span>
          <span className="tnum text-[11px] font-semibold text-fg-100">{fmtMoney(account?.equity ?? account?.balance ?? 10000)}</span>
        </div>
        <div className="flex flex-col items-end border-l border-ink-700 px-3">
          <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-fg-500">Free Margin</span>
          <span className="tnum text-[11px] font-semibold text-fg-100">{fmtMoney(account?.freeMargin ?? 8000)}</span>
        </div>
      </div>

      {/* Feed status */}
      <div className="flex h-full items-center gap-2 border-l border-ink-700 px-3">
        <span className={clsx('h-2 w-2 rounded-full', feedStatus === 'live' && 'bg-bull-500 shadow-[0_0_8px_rgba(22,199,132,0.8)]', feedStatus === 'connecting' && 'bg-gold-400 pulse-dot', feedStatus === 'delayed' && 'bg-bear-500', (feedStatus === 'Demo' || feedStatus === 'closed') && 'bg-fg-500')} />
        <span className="text-[10px] font-medium text-fg-400">{feedStatus}</span>
      </div>

      <KillSwitch live={live} />

      <div className="flex h-full items-center gap-1 border-l border-ink-700 px-2">
        <IconBtn label="Save layout"><Save className="h-3.5 w-3.5" /></IconBtn>
        <IconBtn label="Load layout"><Loader className="h-3.5 w-3.5" /></IconBtn>
        <IconBtn label="Reset layout"><RotateCcw className="h-3.5 w-3.5" /></IconBtn>
      </div>

      <style>{`@keyframes marquee { from { transform: translateX(0) } to { transform: translateX(-50%) } }`}</style>
    </header>
  )
}

function IconBtn({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <button title={label} aria-label={label} className="grid h-7 w-7 place-items-center rounded-md text-fg-500 hover:bg-ink-800 hover:text-fg-200">
      {children}
    </button>
  )
}

function TickerItem({ sym, price }: { sym: string; price: number }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="font-bold text-fg-100">{sym}</span>
      <span className="tnum text-fg-300">{fmtPrice(price)}</span>
    </span>
  )
}

function usePriceFlash(value: number) {
  const prev = useRef(value)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  useEffect(() => {
    if (value !== prev.current) {
      setFlash(value > prev.current ? 'up' : 'down')
      prev.current = value
      const t = window.setTimeout(() => setFlash(null), 450)
      return () => window.clearTimeout(t)
    }
  }, [value])
  return flash
}

function KillSwitch({ live }: { live: boolean }) {
  const [arming, setArming] = useState(false)
  const timer = useRef<number | null>(null)

  const start = () => {
    setArming(true)
    timer.current = window.setTimeout(async () => {
      try {
        await api.kill(live ? 'live' : 'paper')
      } catch {
        /* toast handled by caller */
      }
      setArming(false)
    }, 1500)
  }
  const cancel = () => {
    if (timer.current) window.clearTimeout(timer.current)
    setArming(false)
  }

  return (
    <button
      onPointerDown={start}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      className={clsx('relative mr-2 overflow-hidden rounded-md border px-3 py-2 text-[10px] font-bold uppercase tracking-[0.08em] transition-colors', arming ? 'border-bear-400 bg-bear-500 text-white' : 'border-bear-500/30 bg-ink-800 text-bear-400 hover:bg-bear-500/10')}
      title="Hold 1.5s to kill — reliable halt before cancel/flatten"
    >
      {arming && <span className="absolute inset-0 animate-pulse bg-bear-500/15" />}
      <span className="relative flex items-center gap-1.5">
        <Power className="h-3 w-3" />
        {arming ? 'ARMING…' : 'KILL'}
      </span>
    </button>
  )
}

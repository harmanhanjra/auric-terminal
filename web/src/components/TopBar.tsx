import { clsx } from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { Bot, Command, Power, Radio, ShieldCheck } from 'lucide-react'
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
  onOpenCommand: () => void
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

export function TopBar({
  quote,
  live,
  onToggleLive,
  feedStatus,
  activeSymbol,
  onSelectSymbol,
  onOpenCommand,
}: TopBarProps) {
  const { data: account } = useQuery({
    queryKey: ['account'],
    queryFn: api.account,
    refetchInterval: 10_000,
  })
  const { data: engine } = useQuery({
    queryKey: ['engine-topbar', activeSymbol],
    queryFn: () => api.symbolEngine(activeSymbol),
    refetchInterval: 3000,
  })

  const session = getCurrentSession()
  const priceFlash = usePriceFlash(quote.price)
  const accountConnected = account?.connected === true

  return (
    <header className="auric-topbar relative z-20 flex h-14 shrink-0 items-center border-b backdrop-blur-xl">
      <div className="flex h-full w-[204px] shrink-0 items-center gap-3 border-r border-white/[0.055] px-4">
        <div className="relative grid h-8 w-8 place-items-center rounded-[10px] border border-gold-400/25 bg-gradient-to-b from-gold-400/[0.11] to-ink-900/70 shadow-[0_0_30px_rgba(201,162,39,0.10),inset_0_1px_0_rgba(255,255,255,.05)]">
          <div className="h-3 w-3 rotate-45 rounded-[2px] border border-gold-300/80 bg-gold-400/20" />
          <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-ink-950 bg-bull-500" />
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-black tracking-[-0.03em] text-fg-100">
            AURIC<span className="text-gold-400">/V2</span>
          </div>
          <div className="text-[8px] font-bold uppercase tracking-[0.18em] text-fg-500">
            Execution Terminal
          </div>
        </div>
      </div>

      <SymbolSelector active={activeSymbol} onChange={onSelectSymbol} />

      <div className="flex h-full items-center gap-3 border-r border-white/[0.055] px-4">
        <div>
          <div className="flex items-center gap-1.5 text-[10px] font-bold text-fg-200">
            {activeSymbol}
            <span className="text-[8px] font-medium text-fg-500">{quote.source || '—'}</span>
          </div>
          <div className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.12em] text-fg-600">{session}</div>
        </div>
        <span className={clsx(
          'tnum text-[21px] font-bold leading-none tracking-[-0.035em] text-fg-100',
          priceFlash === 'up' && 'animate-flash-up',
          priceFlash === 'down' && 'animate-flash-down',
        )}>
          {fmtPrice(quote.price)}
        </span>
        <span className="tnum rounded-md border border-white/[0.065] bg-white/[0.035] px-1.5 py-1 text-[9px] text-fg-400">
          SP {fmtPrice(quote.spread)}
        </span>
      </div>

      <div className="hidden min-w-0 flex-1 overflow-hidden xl:block">
        <TickerTape activeSymbol={activeSymbol} activePrice={quote.price} />
      </div>

      <div className="ml-auto flex h-full items-center">
        <div className="hidden h-full items-center gap-4 border-l border-white/[0.055] px-3 lg:flex">
          <Metric label="Balance" value={accountConnected ? fmtMoney(account?.balance ?? 0) : '—'} />
          <Metric label="Equity" value={accountConnected ? fmtMoney(account?.equity ?? 0) : '—'} />
          <Metric label="Free" value={accountConnected ? fmtMoney(account?.freeMargin ?? 0) : '—'} />
        </div>

        <button
          onClick={onOpenCommand}
          className="hidden h-8 items-center gap-2 rounded-lg border border-white/[0.065] bg-white/[0.025] px-2.5 text-[9px] font-bold uppercase tracking-[0.08em] text-fg-500 transition hover:bg-white/[0.05] hover:text-fg-200 xl:flex"
          title="Open command center · Ctrl/⌘ + K"
        >
          <Command className="h-3.5 w-3.5 text-gold-300" />
          <span>Command</span>
          <span className="rounded border border-white/[0.06] px-1.5 py-0.5 text-[7px] text-fg-600">⌘K</span>
        </button>

        <div className="flex h-full items-center gap-2 border-l border-white/[0.055] px-3">
          <span className={clsx(
            'h-1.5 w-1.5 rounded-full',
            feedStatus === 'live' ? 'bg-bull-500 shadow-[0_0_8px_rgba(22,199,132,.8)]' :
            feedStatus === 'delayed' ? 'bg-bear-500' : 'bg-gold-400 pulse-dot',
          )} />
          <span className="text-[8px] font-bold uppercase tracking-[0.12em] text-fg-500">{feedStatus}</span>
        </div>

        <button
          onClick={() => onToggleLive(!live)}
          title="Manual execution environment only. This does not arm the algorithm."
          className={clsx(
            'auric-control mx-2 flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[9px] font-extrabold uppercase tracking-[0.1em] transition-[background-color,border-color,color,box-shadow,transform] duration-200 active:translate-y-px',
            live
              ? 'border-bear-500/35 bg-bear-500/[0.09] text-bear-400 shadow-[0_0_22px_rgba(234,57,67,.06)] hover:bg-bear-500/[0.14]'
              : 'border-gold-400/25 bg-gold-400/[0.075] text-gold-300 shadow-[0_0_22px_rgba(201,162,39,.05)] hover:bg-gold-400/[0.12]',
          )}
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          Manual {live ? 'Live' : 'Paper'}
        </button>

        <div className="hidden items-center gap-1.5 border-l border-white/[0.055] px-3 md:flex">
          <Bot className="h-3.5 w-3.5 text-fg-500" />
          <div>
            <div className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-600">Auto engine</div>
            <div className={clsx('text-[9px] font-extrabold uppercase', engine?.autoLiveEnabled ? 'text-bear-400' : 'text-gold-300')}>
              {engine?.autoLiveEnabled ? 'LIVE-ARM CAPABLE' : 'PAPER ONLY'}
            </div>
          </div>
        </div>

        <KillSwitch live={live} />
      </div>
    </header>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="text-[7px] font-bold uppercase tracking-[0.13em] text-fg-600">{label}</div>
      <div className="tnum text-[10px] font-semibold text-fg-200">{value}</div>
    </div>
  )
}

function TickerTape({ activeSymbol, activePrice }: { activeSymbol: string; activePrice: number }) {
  const { data } = useQuery({
    queryKey: ['ticker-quotes', activeSymbol],
    queryFn: async () => {
      const syms = ['XAUUSD', 'BTCUSD', 'EURUSD']
      const results = await Promise.allSettled(
        syms.map(async (sym) => {
          if (sym === activeSymbol) return { sym, price: activePrice }
          const q = await api.symbolQuote(sym)
          return { sym, price: q.price }
        }),
      )
      return results
        .filter((r): r is PromiseFulfilledResult<{ sym: string; price: number }> => r.status === 'fulfilled')
        .map((r) => r.value)
        .filter((r) => r.price > 0)
    },
    refetchInterval: 12_000,
    staleTime: 8_000,
    retry: false,
  })

  const items = data?.length ? data : [{ sym: activeSymbol, price: activePrice }]
  return (
    <div className="flex h-14 items-center gap-6 overflow-hidden px-4 text-[9px]">
      {items.map((t) => (
        <span key={t.sym} className="flex shrink-0 items-center gap-2">
          <span className="font-extrabold text-fg-300">{t.sym}</span>
          <span className="tnum text-fg-500">{fmtPrice(t.price)}</span>
        </span>
      ))}
    </div>
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
  const [result, setResult] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const start = () => {
    setArming(true)
    setResult(null)
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.kill(live ? 'live' : 'paper')
        setResult(`${r.closed} closed / ${r.cancelled} cancelled`)
      } catch (e) {
        setResult(e instanceof Error ? e.message : 'Kill failed')
      } finally {
        setArming(false)
      }
    }, 1500)
  }

  const cancel = () => {
    if (timer.current) window.clearTimeout(timer.current)
    setArming(false)
  }

  return (
    <div className="relative mr-2">
      <button
        onPointerDown={start}
        onPointerUp={cancel}
        onPointerLeave={cancel}
        className={clsx(
          'auric-control relative overflow-hidden rounded-lg border px-3 py-2 text-[9px] font-black uppercase tracking-[0.1em] transition-[background-color,border-color,color,box-shadow,transform] duration-200 active:translate-y-px',
          arming
            ? 'border-bear-300 bg-bear-500 text-white'
            : 'border-bear-500/30 bg-bear-500/[0.07] text-bear-400 hover:border-bear-400/45 hover:bg-bear-500/[0.14]',
        )}
        title="Hold 1.5 seconds: global Auric halt + cancel + flatten"
      >
        <span className="relative flex items-center gap-1.5">
          {arming ? <Radio className="h-3.5 w-3.5 animate-pulse" /> : <Power className="h-3.5 w-3.5" />}
          {arming ? 'GLOBAL KILL…' : 'KILL ALL'}
        </span>
      </button>
      {result ? (
        <div className="auric-surface auric-surface-elevated absolute right-0 top-11 z-50 w-52 rounded-lg px-2.5 py-2 text-[9px] text-fg-300">
          {result}
        </div>
      ) : null}
    </div>
  )
}

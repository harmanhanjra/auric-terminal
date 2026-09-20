import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Info } from 'lucide-react'
import { fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'

export function DepthPanel({ quote }: { quote: Quote }) {
  const { data, isError } = useQuery({
    queryKey: ['mt5-depth', quote.symbol],
    queryFn: () => api.depth(quote.symbol),
    refetchInterval: 3000,
    retry: false,
  })
  const levels = !isError && data?.available ? data.levels : []
  const ladder = {
    asks: levels.filter(l => l.side === 'ask').sort((a, b) => a.price - b.price).slice(0, 5).map(l => ({ price: l.price, weight: l.volume })),
    bids: levels.filter(l => l.side === 'bid').sort((a, b) => b.price - a.price).slice(0, 5).map(l => ({ price: l.price, weight: l.volume })),
  }
  const max = Math.max(1, ...levels.map(l => l.volume))

  return (
    <section className="border-b border-white/[0.055] bg-ink-900/42 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-[9px] font-extrabold uppercase tracking-[0.12em] text-fg-400">MT5 Market Depth</div>
          <div className="mt-0.5 flex items-center gap-1 text-[8px] text-fg-600">
            <Info className="h-2.5 w-2.5" /> Broker supplied order book
          </div>
        </div>
        <span className="rounded-md border border-white/[0.06] bg-white/[0.025] px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">
          {levels.length ? 'MT5' : 'UNAVAILABLE'}
        </span>
      </div>

      <div className="space-y-px text-[9px]">
        {!levels.length && <p className="py-3 text-fg-500">No broker depth available for {quote.symbol}.</p>}
        {ladder.asks.slice().reverse().map((a, i) => (
          <Level key={`a-${i}`} price={a.price} weight={a.weight} max={max} ask />
        ))}
        <div className="my-1 flex items-center justify-between border-y border-white/[0.055] bg-black/20 px-2 py-1.5">
          <span className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-600">Spread</span>
          <span className="tnum text-[9px] font-bold text-gold-300">{fmtPrice(quote.spread)}</span>
        </div>
        {ladder.bids.map((b, i) => (
          <Level key={`b-${i}`} price={b.price} weight={b.weight} max={max} ask={false} />
        ))}
      </div>
    </section>
  )
}

function Level({ price, weight, max, ask }: { price: number; weight: number; max: number; ask: boolean }) {
  return (
    <div className="relative flex h-5 items-center justify-between overflow-hidden rounded-md px-2">
      <div
        className={`absolute inset-y-0 right-0 ${ask ? 'bg-bear-500/8' : 'bg-bull-500/8'}`}
        style={{ width: `${Math.min(100, weight / max * 100)}%` }}
      />
      <span className={`relative tnum font-semibold ${ask ? 'text-bear-400' : 'text-bull-400'}`}>{fmtPrice(price)}</span>
      <span className="relative tnum text-fg-600">{weight.toLocaleString()}</span>
    </div>
  )
}

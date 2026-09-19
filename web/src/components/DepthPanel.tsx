import { useMemo } from 'react'
import { Info } from 'lucide-react'
import { fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'

export function DepthPanel({ quote }: { quote: Quote }) {
  const p = quote.price || 0
  const sp = Math.max(quote.spread || 0, p ? p * 0.00002 : 0.01)

  // This is intentionally an indicative ladder, not broker L2.  Until a broker
  // depth adapter is connected we never label generated values as market depth.
  const ladder = useMemo(() => {
    const multipliers = [0.6, 1.5, 2.7, 4.1, 5.9]
    const weights = [1.8, 3.7, 6.4, 9.2, 13.0]
    return {
      asks: multipliers.map((m, i) => ({ price: p + sp * m, weight: weights[i] })),
      bids: multipliers.map((m, i) => ({ price: p - sp * m, weight: weights[i] })),
    }
  }, [p, sp])

  const max = 13

  return (
    <section className="border-b border-ink-700/70 bg-ink-900/45 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-[9px] font-extrabold uppercase tracking-[0.12em] text-fg-400">Indicative Liquidity Ladder</div>
          <div className="mt-0.5 flex items-center gap-1 text-[8px] text-fg-600">
            <Info className="h-2.5 w-2.5" /> Generated from spread · not broker L2
          </div>
        </div>
        <span className="rounded border border-ink-700 bg-ink-800 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">
          SYNTHETIC
        </span>
      </div>

      <div className="space-y-px text-[9px]">
        {ladder.asks.slice().reverse().map((a, i) => (
          <Level key={`a-${i}`} price={a.price} weight={a.weight} max={max} ask />
        ))}
        <div className="my-1 flex items-center justify-between border-y border-ink-700/70 bg-ink-950/70 px-2 py-1">
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
    <div className="relative flex h-5 items-center justify-between overflow-hidden rounded-sm px-2">
      <div
        className={`absolute inset-y-0 right-0 ${ask ? 'bg-bear-500/8' : 'bg-bull-500/8'}`}
        style={{ width: `${Math.min(100, weight / max * 100)}%` }}
      />
      <span className={`relative tnum font-semibold ${ask ? 'text-bear-400' : 'text-bull-400'}`}>{fmtPrice(price)}</span>
      <span className="relative tnum text-fg-600">{weight.toFixed(1)} rel</span>
    </div>
  )
}

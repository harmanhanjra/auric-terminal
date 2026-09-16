import { useMemo } from 'react'
import { fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'

export function DepthPanel({ quote }: { quote: Quote }) {
  const p = quote.price || 5000.0
  const sp = quote.spread || 0.18

  // Generate realistic deterministic depth levels relative to current tick
  const depth = useMemo(() => {
    const bids = [
      { price: p - sp * 0.5, size: 2.4, total: 2.4 },
      { price: p - sp * 1.5, size: 4.8, total: 7.2 },
      { price: p - sp * 2.8, size: 8.5, total: 15.7 },
      { price: p - sp * 4.2, size: 12.0, total: 27.7 },
      { price: p - sp * 6.0, size: 18.2, total: 45.9 },
    ]
    const asks = [
      { price: p + sp * 0.5, size: 1.8, total: 1.8 },
      { price: p + sp * 1.6, size: 5.2, total: 7.0 },
      { price: p + sp * 3.0, size: 7.9, total: 14.9 },
      { price: p + sp * 4.5, size: 14.3, total: 29.2 },
      { price: p + sp * 6.5, size: 19.5, total: 48.7 },
    ]
    return { bids, asks }
  }, [p, sp])

  const maxTotal = 50.0

  return (
    <div className="flex flex-col border-b border-ink-700/70 p-3 bg-ink-900/40">
      <div className="flex items-center justify-between pb-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-fg-400">Market Depth (DOM)</span>
        <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[9px] font-semibold text-gold-400">
          L2 · Spread {(quote.spread || 0.18).toFixed(2)}
        </span>
      </div>

      <div className="space-y-0.5 text-[10px]">
        {/* Asks (Sells) reversed so lowest ask is at bottom */}
        {depth.asks.slice().reverse().map((a, i) => (
          <div key={`ask-${i}`} className="relative flex items-center justify-between py-0.5 px-1.5">
            <div
              className="absolute right-0 top-0 bottom-0 bg-bear-500/10 rounded-sm pointer-events-none"
              style={{ width: `${(a.total / maxTotal) * 100}%` }}
            />
            <span className="tnum font-semibold text-bear-400 z-10">{fmtPrice(a.price)}</span>
            <span className="tnum text-fg-400 z-10">{a.size.toFixed(1)}</span>
            <span className="tnum text-fg-500 text-[9px] z-10">{a.total.toFixed(1)}</span>
          </div>
        ))}

        {/* Spread separator */}
        <div className="my-1 flex items-center justify-between border-y border-ink-700/80 bg-ink-800/80 px-2 py-0.5 text-[9px] text-fg-400">
          <span className="font-semibold text-fg-300">Spread</span>
          <span className="tnum font-bold text-gold-400">{fmtPrice(quote.spread || 0.18)}</span>
        </div>

        {/* Bids (Buys) */}
        {depth.bids.map((b, i) => (
          <div key={`bid-${i}`} className="relative flex items-center justify-between py-0.5 px-1.5">
            <div
              className="absolute right-0 top-0 bottom-0 bg-bull-500/10 rounded-sm pointer-events-none"
              style={{ width: `${(b.total / maxTotal) * 100}%` }}
            />
            <span className="tnum font-semibold text-bull-400 z-10">{fmtPrice(b.price)}</span>
            <span className="tnum text-fg-400 z-10">{b.size.toFixed(1)}</span>
            <span className="tnum text-fg-500 text-[9px] z-10">{b.total.toFixed(1)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

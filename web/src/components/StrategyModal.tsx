import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { clsx } from 'clsx'
import { api } from '../lib/api'
import { Modal } from './Modal'

const CATEGORY_META: Record<string, string> = {
  trend: 'Trend',
  mean_reversion: 'Mean reversion',
  structure: 'Structure',
  session: 'Session',
  breakout: 'Breakout',
}

export function StrategyModal() {
  const { data } = useQuery({
    queryKey: ['strategies'],
    queryFn: api.strategies,
    staleTime: 60_000,
  })
  const [active, setActive] = useState<string>('')
  const list = data?.strategies?.length ? data.strategies : FALLBACK

  return (
    <Modal
      id="strategies"
      title="Strategy Engine"
      subtitle="19 signal modules · 7 position-sizing models · validated plain-English decisions"
      badges={['Live signals', 'JSON export', 'Versioned']}
    >
      <div className="grid grid-cols-1 gap-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((s, i) => {
          const cat = CATEGORY_META[s.category] ?? s.category
          const selected = active === s.id
          return (
            <button
              key={s.id}
              onClick={() => setActive(s.id)}
              className={clsx(
                'flex flex-col gap-1 rounded-lg border p-3 text-left transition-all',
                selected
                  ? 'border-gold-600/40 bg-gold-600/5 shadow-[0_0_0_2px_rgba(201,162,39,0.08)]'
                  : 'border-ink-700 bg-ink-800 hover:-translate-y-px hover:border-ink-600 hover:shadow-lg',
              )}
            >
              <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-gold-400">
                {cat}
              </span>
              <span className="text-[12px] font-semibold leading-tight text-fg-100">
                {String(i + 1).padStart(2, '0')} · {s.name}
              </span>
              <span className="text-[9px] text-fg-500">Enabled · M15 · validated parameters</span>
            </button>
          )
        })}
      </div>
    </Modal>
  )
}

const FALLBACK = [
  { id: 'ema144_pullback', name: 'EMA 144 + 9/21 Pullback', category: 'trend' },
  { id: 'triple_ema', name: 'Triple EMA 20/50/200', category: 'trend' },
  { id: 'supertrend_adx', name: 'SuperTrend + ADX', category: 'trend' },
  { id: 'ichimoku', name: 'Ichimoku Kumo Breakout', category: 'trend' },
  { id: 'donchian', name: 'Donchian Turtle Breakout', category: 'trend' },
  { id: 'bb_rsi', name: 'Bollinger Fade + RSI', category: 'mean_reversion' },
  { id: 'vwap_reversion', name: 'VWAP Deviation Reversion', category: 'mean_reversion' },
  { id: 'keltner_squeeze', name: 'Keltner Squeeze Release', category: 'mean_reversion' },
  { id: 'rsi2', name: 'RSI(2) Extremes', category: 'mean_reversion' },
  { id: 'fib_retracement', name: 'Fibonacci Retracement', category: 'structure' },
  { id: 'fib_extension', name: 'Fibonacci Extension', category: 'structure' },
  { id: 'bos_choch', name: 'BOS + CHoCH', category: 'structure' },
  { id: 'orderblock_fvg', name: 'Order Block + FVG', category: 'structure' },
  { id: 'liquidity_sweep', name: 'Liquidity Sweep', category: 'structure' },
  { id: 'sr_bounce', name: 'Support/Resistance Bounce', category: 'structure' },
  { id: 'asia_breakout', name: 'Asian Range Breakout', category: 'session' },
  { id: 'ny_orb', name: 'New York Opening Range', category: 'session' },
  { id: 'atr_expansion', name: 'ATR Expansion Breakout', category: 'breakout' },
  { id: 'momentum_breadth_vol', name: 'Momentum + Breadth + Volatility', category: 'trend' },
] as const
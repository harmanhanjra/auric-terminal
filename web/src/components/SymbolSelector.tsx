import { clsx } from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { api } from '../lib/api'

interface SymbolSelectorProps {
  active: string
  onChange: (symbol: string) => void
}

export function SymbolSelector({ active, onChange }: SymbolSelectorProps) {
  const { data } = useQuery({
    queryKey: ['symbols'],
    queryFn: api.symbols,
    refetchInterval: 15_000,
  })

  const symbols = data?.symbols ?? []
  const list = symbols.length
    ? symbols.map((s) => s.symbol)
    : ['XAUUSD', 'BTCUSD', 'EURUSD']

  const scrollerRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [active])

  const idx = list.indexOf(active)
  const go = (dir: -1 | 1) => {
    if (idx === -1) return onChange(list[0])
    const next = (idx + dir + list.length) % list.length
    onChange(list[next])
  }

  return (
    <div className="flex h-full items-center gap-1 border-r border-white/[0.055] px-2">
      <button
        type="button"
        aria-label="Previous symbol"
        onClick={() => go(-1)}
        className="grid h-7 w-6 place-items-center rounded-lg text-fg-600 hover:bg-white/[0.04] hover:text-fg-200"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <div
        ref={scrollerRef}
        className="flex h-8 max-w-[420px] items-center gap-1 overflow-x-auto rounded-lg border border-white/[0.06] bg-black/16 px-1 scrollbar-hidden"
      >
        {list.map((sym) => (
          <button
            key={sym}
            ref={sym === active ? activeRef : undefined}
            type="button"
            onClick={() => onChange(sym)}
            className={clsx(
              'whitespace-nowrap rounded-md px-2 py-1 text-[9px] font-bold tracking-[0.04em] transition-colors',
              sym === active
                ? 'bg-gold-400/[0.08] text-gold-300 shadow-[inset_0_0_0_1px_rgba(222,190,90,.12)]'
                : 'text-fg-500 hover:bg-white/[0.04] hover:text-fg-200',
            )}
            title={`Switch header to ${sym}`}
          >
            {sym}
          </button>
        ))}
      </div>
      <button
        type="button"
        aria-label="Next symbol"
        onClick={() => go(1)}
        className="grid h-7 w-6 place-items-center rounded-lg text-fg-600 hover:bg-white/[0.04] hover:text-fg-200"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

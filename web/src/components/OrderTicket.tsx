import { useMemo, useState, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { Minus, Plus, TrendingDown, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import { fmtMoney, fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'

interface OrderTicketProps {
  quote: Quote
  live: boolean
}

const OZ_PER_LOT = 100

export function OrderTicket({ quote, live }: OrderTicketProps) {
  const [orderType, setOrderType] = useState<'market' | 'limit' | 'stop'>('market')
  const [lots, setLots] = useState(0.2)
  const [sl, setSl] = useState(4991.2)
  const [tp, setTp] = useState(5046)
  const [status, setStatus] = useState<{ kind: 'success' | 'error'; msg: string } | null>(null)
  const [pending, setPending] = useState(false)

  const riskPct = useMemo(
    () => (sl > 0 ? ((Math.abs(quote.price - sl) / quote.price) * 100).toFixed(2) : '—'),
    [quote.price, sl],
  )
  const rewardPct = useMemo(
    () => (tp > 0 ? ((Math.abs(tp - quote.price) / quote.price) * 100).toFixed(2) : '—'),
    [quote.price, tp],
  )
  const rr = useMemo(() => {
    const reward = Math.abs(tp - quote.price)
    const risk = Math.abs(quote.price - sl)
    return risk > 0 ? (reward / risk).toFixed(2) : '—'
  }, [quote.price, sl, tp])

  const margin = lots * OZ_PER_LOT * quote.price
  const atStop = -(lots * OZ_PER_LOT * Math.abs(quote.price - sl))
  const atTarget = lots * OZ_PER_LOT * Math.abs(tp - quote.price)

  const adjustLots = (delta: number) =>
    setLots((v) => Math.min(5, Math.max(0.1, Math.round((v + delta) * 100) / 100)))

  const submit = async (side: 'buy' | 'sell') => {
    setPending(true)
    setStatus(null)
    try {
      const res = await api.order({
        side,
        lots,
        stop_loss: orderType === 'market' ? sl : null,
        take_profit: orderType === 'market' ? tp : null,
        mode: live ? 'live' : 'paper',
        client_order_id: `auric-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      })
      setStatus({
        kind: 'success',
        msg: `${(live ? 'LIVE' : 'PAPER')} ${side.toUpperCase()} ${lots.toFixed(2)} @ ${fmtPrice(res.fillPrice)}`,
      })
    } catch (e) {
      setStatus({ kind: 'error', msg: e instanceof Error ? e.message : 'Order rejected' })
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 border-b border-ink-700/70 p-3">
      <div className="flex rounded-md border border-ink-700 bg-ink-800 p-0.5">
        {(['market', 'limit', 'stop'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setOrderType(t)}
            className={clsx(
              'flex-1 rounded py-1 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
              orderType === t ? 'bg-ink-700 text-fg-100' : 'text-fg-500 hover:text-fg-300',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Size · Lots">
          <div className="flex items-center justify-between gap-1">
            <button
              onClick={() => adjustLots(-0.1)}
              className="grid h-7 w-7 place-items-center rounded bg-ink-700 text-fg-200 hover:bg-ink-600"
              aria-label="Decrease lots"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <span className="tnum text-[13px] font-semibold text-fg-100">{lots.toFixed(2)}</span>
            <button
              onClick={() => adjustLots(0.1)}
              className="grid h-7 w-7 place-items-center rounded bg-ink-700 text-fg-200 hover:bg-ink-600"
              aria-label="Increase lots"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </Field>
        <Field label="Risk · USD">
          <Input value={250} prefix="$" />
        </Field>

        <Field label={`Stop loss · ${riskPct}%`}>
          <Input value={sl} onChange={(v) => setSl(Number(v))} />
        </Field>
        <Field label={`Take profit · ${rewardPct}%`}>
          <Input value={tp} onChange={(v) => setTp(Number(v))} />
        </Field>
      </div>

      <div className="flex items-center justify-between border-t border-ink-700/70 pt-2 text-[10px] text-fg-400">
        <span>Risk / Reward</span>
        <span className="tnum text-[13px] font-semibold text-gold-400">1 : {rr}</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          disabled={pending}
          onClick={() => submit('sell')}
          className="flex h-11 flex-col items-center justify-center rounded-lg bg-gradient-to-br from-bear-500 to-bear-600 text-white shadow-[0_4px_14px_rgba(0,0,0,0.35)] transition-transform hover:-translate-y-px hover:shadow-[0_6px_18px_rgba(234,57,67,0.25)] disabled:opacity-50"
        >
          <span className="flex items-center gap-1 text-[11px] font-extrabold uppercase tracking-[0.08em]">
            <TrendingDown className="h-3.5 w-3.5" /> Sell
          </span>
          <span className="tnum text-[9px] font-medium opacity-70">{fmtPrice(quote.bid || quote.price)}</span>
        </button>
        <button
          disabled={pending}
          onClick={() => submit('buy')}
          className="flex h-11 flex-col items-center justify-center rounded-lg bg-gradient-to-br from-bull-500 to-[#0e8a5a] text-white shadow-[0_4px_14px_rgba(0,0,0,0.35)] transition-transform hover:-translate-y-px hover:shadow-[0_6px_18px_rgba(22,199,132,0.25)] disabled:opacity-50"
        >
          <span className="flex items-center gap-1 text-[11px] font-extrabold uppercase tracking-[0.08em]">
            <TrendingUp className="h-3.5 w-3.5" /> Buy
          </span>
          <span className="tnum text-[9px] font-medium opacity-70">{fmtPrice(quote.ask)}</span>
        </button>
      </div>

      <div className="grid grid-cols-3 gap-1.5 rounded-md border border-ink-700/70 bg-ink-800 p-2">
        <Summary label="Margin" value={fmtMoney(margin)} />
        <Summary label="At stop" value={fmtMoney(atStop)} tone="text-bear-500" />
        <Summary label="At target" value={fmtMoney(atTarget)} tone="text-bull-500" />
      </div>

      {status && (
        <div
          className={clsx(
            'rounded-md border px-2 py-1.5 text-[10px]',
            status.kind === 'success'
              ? 'border-bull-500/30 bg-bull-500/10 text-bull-500'
              : 'border-bear-500/30 bg-bear-500/10 text-bear-400',
          )}
          aria-live="polite"
        >
          {status.msg}
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-fg-500">{label}</span>
      {children}
    </label>
  )
}

function Input({
  value,
  onChange,
  prefix,
  ariaLabel,
}: {
  value: number | string
  onChange?: (v: number | string) => void
  prefix?: string
  ariaLabel?: string
}) {
  return (
    <div className="flex h-8 items-center gap-1 rounded-md border border-ink-700 bg-ink-800 px-2 focus-within:border-ink-500">
      {prefix && <span className="text-[11px] text-fg-500">{prefix}</span>}
      <input
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        className="tnum w-full bg-transparent text-right text-[12px] text-fg-100 outline-none"
        inputMode="decimal"
        aria-label={ariaLabel ?? 'value'}
      />
    </div>
  )
}

function Summary({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: string
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-500">{label}</span>
      <span className={clsx('tnum text-[12px] font-semibold text-fg-100', tone)}>{value}</span>
    </div>
  )
}

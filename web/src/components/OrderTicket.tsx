import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Calculator, LockKeyhole, TrendingDown, TrendingUp } from 'lucide-react'
import { api, getLiveKey, setLiveKey } from '../lib/api'
import { fmtMoney, fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'
import { Button } from './ui/Button'

interface OrderTicketProps {
  quote: Quote
  live: boolean
  activeSymbol?: string
}

type OrderType = 'market' | 'limit' | 'stop'
type SizingMode = 'risk' | 'lots'

function decimalsFor(symbol: string) {
  return symbol === 'EURUSD' ? 5 : 2
}

function roundFor(symbol: string, value: number) {
  const d = decimalsFor(symbol)
  const m = 10 ** d
  return Math.round(value * m) / m
}

export function OrderTicket({ quote, live, activeSymbol = 'XAUUSD' }: OrderTicketProps) {
  const [orderType, setOrderType] = useState<OrderType>('market')
  const [sizingMode, setSizingMode] = useState<SizingMode>('risk')
  const [manualLots, setManualLots] = useState(0.1)
  const [riskUsd, setRiskUsd] = useState(50)
  const [entryPrice, setEntryPrice] = useState(quote.price)
  const [sl, setSl] = useState(quote.price * 0.996)
  const [tp, setTp] = useState(quote.price * 1.008)
  const [status, setStatus] = useState<{ kind: 'success' | 'error'; msg: string } | null>(null)
  const [pending, setPending] = useState(false)
  const [liveKey, setLiveKeyState] = useState(() => getLiveKey())

  useEffect(() => {
    if (quote.price <= 0) return
    setEntryPrice(roundFor(activeSymbol, quote.price))
    setSl(roundFor(activeSymbol, quote.price * 0.996))
    setTp(roundFor(activeSymbol, quote.price * 1.008))
    setStatus(null)
    // Re-anchor only when the instrument changes; live ticks must not overwrite
    // a trader's edited entry/SL/TP.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSymbol])

  const effectiveEntry = orderType === 'market' ? quote.price : entryPrice
  const previewEnabled =
    effectiveEntry > 0 &&
    sl > 0 &&
    Math.abs(effectiveEntry - sl) > Number.EPSILON &&
    riskUsd > 0

  const { data: preview } = useQuery({
    queryKey: ['risk-preview', activeSymbol, effectiveEntry, sl, tp, riskUsd],
    queryFn: () =>
      api.riskPreview({
        symbol: activeSymbol,
        side: 'buy',
        entry: effectiveEntry,
        stop: sl,
        target: tp || null,
        risk_amount: riskUsd,
      }),
    enabled: previewEnabled,
    staleTime: 1200,
    refetchInterval: 4000,
    retry: false,
  })

  const lots = sizingMode === 'risk' ? (preview?.lots ?? manualLots) : manualLots
  const rr = preview?.rr ?? (() => {
    const risk = Math.abs(effectiveEntry - sl)
    return risk > 0 ? Math.abs(tp - effectiveEntry) / risk : 0
  })()

  const adjustLots = (delta: number) => {
    setManualLots((v) => Math.max(0.01, Math.round((v + delta) * 100) / 100))
    setSizingMode('lots')
  }

  const submit = async (side: 'buy' | 'sell') => {
    setPending(true)
    setStatus(null)
    try {
      const res = await api.order({
        side,
        lots,
        order_type: orderType,
        entry_price: orderType === 'market' ? null : entryPrice,
        stop_loss: sl || null,
        take_profit: tp || null,
        mode: live ? 'live' : 'paper',
        symbol: activeSymbol,
        client_order_id: `auric-v2-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      })
      const state = res.status === 'pending' ? 'PENDING' : 'FILLED'
      const px = res.fillPrice ?? res.entryPrice ?? entryPrice
      setStatus({
        kind: 'success',
        msg: `${live ? 'LIVE' : 'PAPER'} · ${state} · ${side.toUpperCase()} ${lots} @ ${fmtPrice(px)}`,
      })
    } catch (e) {
      setStatus({ kind: 'error', msg: e instanceof Error ? e.message : 'Order rejected' })
    } finally {
      setPending(false)
    }
  }

  const riskLabel = sizingMode === 'risk' ? 'Risk-sized' : 'Manual lots'
  const priceDeltaPct = useMemo(
    () => (effectiveEntry > 0 ? Math.abs(effectiveEntry - sl) / effectiveEntry * 100 : 0),
    [effectiveEntry, sl],
  )

  return (
    <section className="border-b border-white/[0.055] bg-ink-900/58 p-3">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-fg-300">
            Execution Ticket
          </div>
          <div className="mt-0.5 text-[9px] text-fg-500">
            {activeSymbol} · {live ? 'manual live' : 'paper broker'} · algo arming is separate
          </div>
        </div>
        <span className={clsx(
          'rounded-md border px-2 py-1 text-[9px] font-extrabold uppercase tracking-[0.12em]',
          live
            ? 'border-bear-500/35 bg-bear-500/10 text-bear-400'
            : 'border-gold-600/35 bg-gold-600/10 text-gold-300',
        )}>
          {live ? 'LIVE' : 'PAPER'}
        </span>
      </div>

      <div className="mb-3 grid grid-cols-3 rounded-xl border border-white/[0.06] bg-black/18 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,.02)]">
        {(['market', 'limit', 'stop'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setOrderType(t)}
            className={clsx(
              'rounded-lg py-1.5 text-[9px] font-extrabold uppercase tracking-[0.12em] transition-colors',
              orderType === t
                ? 'bg-white/[0.07] text-fg-100 shadow-[inset_0_0_0_1px_rgba(255,255,255,.045)]'
                : 'text-fg-500 hover:bg-white/[0.04] hover:text-fg-300',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        {orderType !== 'market' && (
          <Field label="Entry price">
            <Input value={entryPrice} onChange={(v) => setEntryPrice(Number(v))} />
          </Field>
        )}

        <Field label="Sizing model">
          <div className="grid h-8 grid-cols-2 rounded-lg border border-white/[0.06] bg-black/18 p-0.5">
            <button
              onClick={() => setSizingMode('risk')}
              className={clsx('rounded text-[9px] font-bold', sizingMode === 'risk' ? 'bg-gold-600/20 text-gold-300' : 'text-fg-500')}
            >
              Risk
            </button>
            <button
              onClick={() => setSizingMode('lots')}
              className={clsx('rounded text-[9px] font-bold', sizingMode === 'lots' ? 'bg-ink-700 text-fg-200' : 'text-fg-500')}
            >
              Lots
            </button>
          </div>
        </Field>

        {sizingMode === 'risk' ? (
          <Field label="Max risk · USD">
            <Input value={riskUsd} prefix="$" onChange={(v) => setRiskUsd(Math.max(1, Number(v)))} />
          </Field>
        ) : (
          <Field label="Size · lots">
            <div className="auric-field flex h-8 items-center justify-between rounded-lg px-1">
              <button onClick={() => adjustLots(-0.01)} className="h-6 w-7 rounded text-fg-400 hover:bg-ink-700" aria-label="Decrease lots">−</button>
              <span className="tnum text-[12px] font-semibold text-fg-100">{manualLots.toFixed(2)}</span>
              <button onClick={() => adjustLots(0.01)} className="h-6 w-7 rounded text-fg-400 hover:bg-ink-700" aria-label="Increase lots">+</button>
            </div>
          </Field>
        )}

        <Field label={`Stop loss · ${priceDeltaPct.toFixed(2)}%`}>
          <Input value={sl} onChange={(v) => setSl(Number(v))} />
        </Field>
        <Field label="Take profit">
          <Input value={tp} onChange={(v) => setTp(Number(v))} />
        </Field>
      </div>

      <div className="auric-surface mt-3 rounded-xl p-2.5">
        <div className="mb-2 flex items-center justify-between text-[9px]">
          <span className="flex items-center gap-1 font-bold uppercase tracking-[0.1em] text-fg-500">
            <Calculator className="h-3 w-3" /> Broker-aware sizing
          </span>
          <span className="font-semibold text-gold-300">{riskLabel}</span>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <Summary label="Lots" value={lots ? String(lots) : '—'} />
          <Summary label="Risk" value={preview ? fmtMoney(-preview.riskUsd) : '—'} tone="text-bear-400" />
          <Summary label="Reward" value={preview?.rewardUsd != null ? fmtMoney(preview.rewardUsd) : '—'} tone="text-bull-400" />
          <Summary label="R:R" value={rr ? `1:${Number(rr).toFixed(2)}` : '—'} tone="text-gold-300" />
        </div>
        <div className="mt-2 flex items-center justify-between border-t border-white/[0.055] pt-2 text-[9px] text-fg-500">
          <span>Margin estimate</span>
          <span className="tnum text-fg-300">{preview?.margin != null ? fmtMoney(preview.margin) : 'Broker quote required'}</span>
        </div>
      </div>

      {live && (
        <div className="mt-3">
          <Field label="Live execution key">
            <div className="auric-field flex h-8 items-center gap-2 rounded-lg px-2">
              <LockKeyhole className="h-3.5 w-3.5 text-fg-500" />
              <input
                type="password"
                value={liveKey}
                onChange={(e) => {
                  const value = e.target.value.trim()
                  setLiveKeyState(value)
                  setLiveKey(value)
                }}
                placeholder="Required for live mutations"
                autoComplete="off"
                className="w-full bg-transparent text-[11px] text-fg-100 outline-none placeholder:text-fg-600"
                aria-label="Live execution key"
              />
            </div>
          </Field>
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button
          variant="sell"
          disabled={pending || lots <= 0}
          onClick={() => submit('sell')}
          className="group h-12 justify-between rounded-xl px-3"
        >
          <span className="flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.08em]">
            <TrendingDown className="h-4 w-4" /> Sell
          </span>
          <span className="tnum text-[10px] text-white/75">{fmtPrice(quote.bid || quote.price)}</span>
        </Button>
        <Button
          variant="primary"
          disabled={pending || lots <= 0}
          onClick={() => submit('buy')}
          className="group h-12 justify-between rounded-xl px-3"
        >
          <span className="flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.08em]">
            <TrendingUp className="h-4 w-4" /> Buy
          </span>
          <span className="tnum text-[10px] text-white/75">{fmtPrice(quote.ask || quote.price)}</span>
        </Button>
      </div>

      {status && (
        <div
          className={clsx(
            'mt-3 rounded-md border px-2.5 py-2 text-[10px]',
            status.kind === 'success'
              ? 'border-bull-500/30 bg-bull-500/10 text-bull-400'
              : 'border-bear-500/30 bg-bear-500/10 text-bear-400',
          )}
          aria-live="polite"
        >
          {status.msg}
        </div>
      )}
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="truncate text-[8px] font-bold uppercase tracking-[0.12em] text-fg-500">{label}</span>
      {children}
    </label>
  )
}

function Input({
  value,
  onChange,
  prefix,
}: {
  value: number | string
  onChange?: (v: number | string) => void
  prefix?: string
}) {
  return (
    <div className="auric-field flex h-8 items-center gap-1 rounded-lg px-2">
      {prefix ? <span className="text-[10px] text-fg-500">{prefix}</span> : null}
      <input
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        className="tnum w-full min-w-0 bg-transparent text-right text-[11px] text-fg-100 outline-none"
        inputMode="decimal"
      />
    </div>
  )
}

function Summary({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[8px] font-bold uppercase tracking-[0.1em] text-fg-600">{label}</div>
      <div className={clsx('tnum truncate text-[11px] font-semibold text-fg-100', tone)}>{value}</div>
    </div>
  )
}

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Target,
  History,
  ShieldAlert,
  Activity,
  Terminal,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react'
import { api } from '../lib/api'
import { fmtMoney, fmtPrice } from '../lib/format'
import type { Quote } from '../lib/types'

interface DockProps {
  quote: Quote
  live: boolean
  view: string
  onNavigate: (key: string) => void
}

type DockTab = 'positions' | 'journal' | 'risk' | 'signals' | 'logs'

export function Dock({ live, onNavigate }: DockProps) {
  const [activeTab, setActiveTab] = useState<DockTab>('positions')
  const [actionTicket, setActionTicket] = useState<number | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  // Queries connected to backend endpoints
  const { data: positionsData, refetch: refetchPositions } = useQuery({
    queryKey: ['positions', live],
    queryFn: () => api.positions(live ? 'live' : 'paper'),
    refetchInterval: 3000,
  })

  const { data: journalData, refetch: refetchJournal } = useQuery({
    queryKey: ['journal'],
    queryFn: () => api.journal(50),
    refetchInterval: 5000,
  })

  const { data: engineData, refetch: refetchEngine } = useQuery({
    queryKey: ['engine'],
    queryFn: api.engine,
    refetchInterval: 3000,
  })

  const { data: accountData } = useQuery({
    queryKey: ['account'],
    queryFn: api.account,
    refetchInterval: 5000,
  })

  const positions = positionsData?.positions ?? []
  const journalEntries = journalData?.entries ?? []
  const engineLog = engineData?.log ?? []
  const engineRisk = engineData?.risk

  const totalPnl = positions.reduce((acc, p) => acc + (p.pnl || 0), 0)

  const runPositionAction = async (
    ticket: number,
    action: 'breakeven' | 'half' | 'close',
    lots: number,
  ) => {
    setActionTicket(ticket)
    setActionMessage(null)
    try {
      if (action === 'breakeven') {
        await api.protectPosition(ticket, live ? 'live' : 'paper', { breakeven: true })
      } else {
        const closeLots = action === 'half' ? Math.max(0.01, lots / 2) : undefined
        await api.closePosition(ticket, live ? 'live' : 'paper', closeLots)
      }
      setActionMessage(
        action === 'breakeven' ? `#${ticket} moved to breakeven` : `#${ticket} close request accepted`,
      )
      await Promise.all([refetchPositions(), refetchJournal()])
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : 'Position action failed')
    } finally {
      setActionTicket(null)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-ink-900 text-fg-200">
      {/* Dock Tab Bar */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-ink-700/70 bg-ink-950/80 px-3">
        <div className="flex items-center gap-1">
          <button
            onClick={() => setActiveTab('positions')}
            className={clsx(
              'flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold transition-colors',
              activeTab === 'positions'
                ? 'bg-ink-800 text-gold-400 border border-gold-600/30'
                : 'text-fg-400 hover:bg-ink-800/60 hover:text-fg-200',
            )}
          >
            <Target className="h-3.5 w-3.5" />
            <span>Open Positions</span>
            {positions.length > 0 && (
              <span className="rounded-full bg-gold-600/20 px-1.5 py-0.2 text-[9px] font-bold text-gold-300">
                {positions.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('journal')}
            className={clsx(
              'flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold transition-colors',
              activeTab === 'journal'
                ? 'bg-ink-800 text-gold-400 border border-gold-600/30'
                : 'text-fg-400 hover:bg-ink-800/60 hover:text-fg-200',
            )}
          >
            <History className="h-3.5 w-3.5" />
            <span>Trade Journal</span>
            {journalEntries.length > 0 && (
              <span className="rounded-full bg-ink-700 px-1.5 py-0.2 text-[9px] font-semibold text-fg-400">
                {journalEntries.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('signals')}
            className={clsx(
              'flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold transition-colors',
              activeTab === 'signals'
                ? 'bg-ink-800 text-gold-400 border border-gold-600/30'
                : 'text-fg-400 hover:bg-ink-800/60 hover:text-fg-200',
            )}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>Active Signals</span>
            {engineData?.signal && (
              <span className="h-1.5 w-1.5 rounded-full bg-bull-500 shadow-[0_0_6px_rgba(22,199,132,0.8)]" />
            )}
          </button>

          <button
            onClick={() => setActiveTab('risk')}
            className={clsx(
              'flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold transition-colors',
              activeTab === 'risk'
                ? 'bg-ink-800 text-gold-400 border border-gold-600/30'
                : 'text-fg-400 hover:bg-ink-800/60 hover:text-fg-200',
            )}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>Risk Radar</span>
            {engineRisk?.halted && (
              <span className="rounded bg-bear-500/20 px-1.5 py-0.2 text-[9px] font-bold text-bear-400">
                HALTED
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('logs')}
            className={clsx(
              'flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold transition-colors',
              activeTab === 'logs'
                ? 'bg-ink-800 text-gold-400 border border-gold-600/30'
                : 'text-fg-400 hover:bg-ink-800/60 hover:text-fg-200',
            )}
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>Engine Logs</span>
          </button>
        </div>

        {/* Right Info Bar */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-fg-500">Floating P/L:</span>
            <span
              className={clsx(
                'tnum font-bold',
                totalPnl > 0 ? 'text-bull-500' : totalPnl < 0 ? 'text-bear-500' : 'text-fg-300',
              )}
            >
              {totalPnl >= 0 ? `+${fmtMoney(totalPnl)}` : fmtMoney(totalPnl)}
            </span>
          </div>
          <button
            onClick={() => {
              refetchPositions()
              refetchJournal()
              refetchEngine()
            }}
            title="Refresh tables"
            className="grid h-6 w-6 place-items-center rounded text-fg-500 hover:bg-ink-800 hover:text-fg-200"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {actionMessage ? (
        <div className="shrink-0 border-b border-ink-700/60 bg-ink-950/80 px-3 py-1 text-[9px] text-fg-400" aria-live="polite">
          {actionMessage}
        </div>
      ) : null}

      {/* Dock Content Body */}
      <div className="min-h-0 flex-1 overflow-auto p-2">
        {/* TAB 1: POSITIONS */}
        {activeTab === 'positions' && (
          <div>
            {positions.length === 0 ? (
              <div className="flex h-44 flex-col items-center justify-center gap-1.5 text-fg-500">
                <Target className="h-7 w-7 stroke-[1.2] opacity-40" />
                <span className="text-[12px] font-medium">No open positions on {live ? 'LIVE' : 'PAPER'}</span>
                <span className="text-[10px] text-fg-500">
                  Execute orders via the Order Ticket or let the strategy engine trigger automated entries.
                </span>
              </div>
            ) : (
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="border-b border-ink-700/70 text-[9px] font-bold uppercase tracking-[0.1em] text-fg-500">
                    <th className="pb-1.5 pl-2 font-medium">Symbol</th>
                    <th className="pb-1.5 font-medium">Side</th>
                    <th className="pb-1.5 font-medium">Volume</th>
                    <th className="pb-1.5 font-medium">Entry Price</th>
                    <th className="pb-1.5 font-medium">Current Price</th>
                    <th className="pb-1.5 font-medium">Stop Loss</th>
                    <th className="pb-1.5 font-medium">Take Profit</th>
                    <th className="pb-1.5 text-right font-medium">Net P/L</th>
                    <th className="pb-1.5 pr-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800/60">
                  {positions.map((p, i) => {
                    const isBuy = p.side.toLowerCase() === 'buy'
                    return (
                      <tr key={p.ticket ?? i} className="hover:bg-ink-800/40">
                        <td className="py-2 pl-2 font-bold text-fg-100">{p.symbol}</td>
                        <td className="py-2">
                          <span
                            className={clsx(
                              'inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide',
                              isBuy ? 'bg-bull-500/15 text-bull-400' : 'bg-bear-500/15 text-bear-400',
                            )}
                          >
                            {isBuy ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                            {p.side}
                          </span>
                        </td>
                        <td className="tnum py-2 font-medium text-fg-200">{p.lots.toFixed(2)}</td>
                        <td className="tnum py-2 text-fg-300">{fmtPrice(p.entry)}</td>
                        <td className="tnum py-2 text-fg-100">{fmtPrice(p.market)}</td>
                        <td className="tnum py-2 text-fg-400">{p.sl ? fmtPrice(p.sl) : '—'}</td>
                        <td className="tnum py-2 text-fg-400">{p.tp ? fmtPrice(p.tp) : '—'}</td>
                        <td
                          className={clsx(
                            'tnum py-2 text-right font-bold',
                            p.pnl > 0 ? 'text-bull-500' : p.pnl < 0 ? 'text-bear-500' : 'text-fg-300',
                          )}
                        >
                          {p.pnl >= 0 ? `+${fmtMoney(p.pnl)}` : fmtMoney(p.pnl)}
                        </td>
                        <td className="py-1.5 pr-2">
                          <div className="flex justify-end gap-1">
                            <button
                              disabled={!p.ticket || actionTicket === p.ticket}
                              onClick={() => p.ticket && runPositionAction(p.ticket, 'breakeven', p.lots)}
                              className="rounded border border-ink-700 bg-ink-800 px-1.5 py-1 text-[8px] font-bold text-gold-300 hover:bg-ink-700 disabled:opacity-30"
                              title="Move stop loss to entry price"
                            >
                              BE
                            </button>
                            <button
                              disabled={!p.ticket || actionTicket === p.ticket || p.lots <= 0.01}
                              onClick={() => p.ticket && runPositionAction(p.ticket, 'half', p.lots)}
                              className="rounded border border-ink-700 bg-ink-800 px-1.5 py-1 text-[8px] font-bold text-fg-300 hover:bg-ink-700 disabled:opacity-30"
                              title="Close half of the position"
                            >
                              ½
                            </button>
                            <button
                              disabled={!p.ticket || actionTicket === p.ticket}
                              onClick={() => p.ticket && runPositionAction(p.ticket, 'close', p.lots)}
                              className="rounded border border-bear-500/25 bg-bear-500/8 px-1.5 py-1 text-[8px] font-bold text-bear-400 hover:bg-bear-500/15 disabled:opacity-30"
                              title="Close the full position"
                            >
                              Close
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* TAB 2: TRADE JOURNAL */}
        {activeTab === 'journal' && (
          <div>
            {journalEntries.length === 0 ? (
              <div className="flex h-44 flex-col items-center justify-center gap-1.5 text-fg-500">
                <History className="h-7 w-7 stroke-[1.2] opacity-40" />
                <span className="text-[12px] font-medium">Trade journal is empty</span>
                <span className="text-[10px] text-fg-500">Closed trades and lifecycle events are logged to auric.db SQLite store.</span>
              </div>
            ) : (
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="border-b border-ink-700/70 text-[9px] font-bold uppercase tracking-[0.1em] text-fg-500">
                    <th className="pb-1.5 pl-2 font-medium">Timestamp</th>
                    <th className="pb-1.5 font-medium">Mode</th>
                    <th className="pb-1.5 font-medium">Side</th>
                    <th className="pb-1.5 font-medium">Lots</th>
                    <th className="pb-1.5 font-medium">Entry Price</th>
                    <th className="pb-1.5 font-medium">Strategy</th>
                    <th className="pb-1.5 font-medium">Execution Reason</th>
                    <th className="pb-1.5 pr-2 text-right font-medium">P/L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800/60">
                  {journalEntries.map((j, i) => (
                    <tr key={j.id ?? i} className="hover:bg-ink-800/40">
                      <td className="py-2 pl-2 text-[10px] text-fg-400">
                        {typeof j.ts === 'number' ? new Date(j.ts).toLocaleTimeString() : String(j.ts)}
                      </td>
                      <td className="py-2">
                        <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[9px] font-bold uppercase text-fg-300">
                          {j.mode}
                        </span>
                      </td>
                      <td className="py-2">
                        <span
                          className={clsx(
                            'rounded px-1.5 py-0.5 text-[9px] font-bold uppercase',
                            j.side.toLowerCase() === 'buy'
                              ? 'bg-bull-500/15 text-bull-400'
                              : 'bg-bear-500/15 text-bear-400',
                          )}
                        >
                          {j.side}
                        </span>
                      </td>
                      <td className="tnum py-2 text-fg-200">{j.lots?.toFixed(2) ?? '—'}</td>
                      <td className="tnum py-2 text-fg-300">{j.entry ? fmtPrice(j.entry) : '—'}</td>
                      <td className="py-2 text-[10px] text-gold-300">{j.strategy ?? 'Manual'}</td>
                      <td className="py-2 text-[10px] text-fg-400">{j.reason ?? '—'}</td>
                      <td
                        className={clsx(
                          'tnum py-2 pr-2 text-right font-bold',
                          (j.pnl ?? 0) > 0 ? 'text-bull-500' : (j.pnl ?? 0) < 0 ? 'text-bear-500' : 'text-fg-400',
                        )}
                      >
                        {j.pnl !== undefined && j.pnl !== null ? fmtMoney(j.pnl) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* TAB 3: SIGNALS */}
        {activeTab === 'signals' && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Active Strategy Signal</div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-[14px] font-bold text-fg-100">
                  {engineData?.strategy ? engineData.strategy.replace(/_/g, ' ').toUpperCase() : 'EMA144 PULLBACK'}
                </span>
                <span
                  className={clsx(
                    'rounded px-2 py-0.5 text-[10px] font-bold uppercase',
                    engineData?.signal?.side === 1
                      ? 'bg-bull-500/20 text-bull-400'
                      : engineData?.signal?.side === -1
                        ? 'bg-bear-500/20 text-bear-400'
                        : 'bg-ink-700 text-fg-400',
                  )}
                >
                  {engineData?.signal?.side === 1
                    ? 'BUY'
                    : engineData?.signal?.side === -1
                      ? 'SELL'
                      : 'NEUTRAL'}
                </span>
              </div>
              <div className="mt-2 text-[10px] text-fg-400">
                Reason: <span className="text-fg-200">{engineData?.signal?.reason || 'Monitoring price action & indicator bands'}</span>
              </div>
            </div>

            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Engine Execution Mode</div>
              <div className="mt-2 flex items-center gap-2">
                <span
                  className={clsx(
                    'h-2 w-2 rounded-full',
                    engineData?.running ? 'bg-bull-500 shadow-[0_0_8px_rgba(22,199,132,0.8)]' : 'bg-gold-400',
                  )}
                />
                <span className="text-[13px] font-bold text-fg-100 capitalize">
                  {engineData?.status || 'Active Loop'}
                </span>
                <span className="ml-auto rounded bg-ink-700 px-2 py-0.5 text-[9px] font-semibold text-fg-300">
                  TF: {engineData?.timeframe || 'M15'}
                </span>
              </div>
              <div className="mt-2 flex items-center justify-between text-[10px] text-fg-400">
                <span>Trades Executed: <strong className="text-fg-200">{engineData?.trades ?? 0}</strong></span>
                <span>Pyramids: <strong className="text-fg-200">{engineData?.pyramids ?? 0}</strong></span>
              </div>
            </div>

            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Strategy Matrix Quick Launch</div>
              <p className="mt-1 text-[10px] text-fg-400">Access 19 algorithmic models and multi-timeframe backtesting.</p>
              <button
                onClick={() => onNavigate('strategies')}
                className="mt-2 flex items-center gap-1 rounded bg-gold-600/20 px-2.5 py-1 text-[10px] font-bold text-gold-300 ring-1 ring-gold-600/30 hover:bg-gold-600/30"
              >
                <Layers className="h-3 w-3" /> Open Strategy Engine
              </button>
            </div>
          </div>
        )}

        {/* TAB 4: RISK RADAR */}
        {activeTab === 'risk' && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Daily Loss Limit Check</div>
              <div className="mt-1.5 flex items-baseline justify-between">
                <span className="text-[16px] font-bold text-fg-100">
                  {fmtMoney(engineRisk?.realized ?? 0)}
                </span>
                <span className="text-[10px] text-fg-400">
                  Max: {fmtMoney(engineRisk?.dailyLoss ?? 500)}
                </span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-ink-700">
                <div
                  className={clsx(
                    'h-full transition-all',
                    (engineRisk?.realized ?? 0) < 0 ? 'bg-bear-500' : 'bg-bull-500',
                  )}
                  style={{
                    width: `${Math.min(100, (Math.abs(engineRisk?.realized ?? 0) / (engineRisk?.dailyLoss || 500)) * 100)}%`,
                  }}
                />
              </div>
            </div>

            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Circuit Breaker Status</div>
              <div className="mt-2 flex items-center gap-2">
                {engineRisk?.halted ? (
                  <>
                    <AlertTriangle className="h-4 w-4 text-bear-500" />
                    <span className="text-[13px] font-bold text-bear-400">TRADING HALTED</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-bull-500" />
                    <span className="text-[13px] font-bold text-bull-400">SYSTEM NORMAL · ARMED</span>
                  </>
                )}
              </div>
              <div className="mt-2 text-[10px] text-fg-400">
                Auto-halt triggers if daily drawdown exceeds threshold.
              </div>
            </div>

            <div className="rounded-lg border border-ink-700 bg-ink-800/80 p-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-fg-500">Account Free Margin Level</div>
              <div className="mt-1.5 flex items-baseline justify-between">
                <span className="text-[16px] font-bold text-fg-100">
                  {fmtMoney(accountData?.freeMargin ?? 8000)}
                </span>
                <span className="text-[10px] text-bull-400 font-semibold">100% HEALTHY</span>
              </div>
              <div className="mt-2 text-[10px] text-fg-400">
                Currency: <strong className="text-fg-200">{accountData?.currency || 'USD'}</strong> · Leverage 1:100
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: ENGINE LOGS */}
        {activeTab === 'logs' && (
          <div className="h-48 overflow-y-auto rounded bg-ink-950 p-2 font-mono text-[10px] text-fg-300">
            {engineLog.length === 0 ? (
              <div className="text-fg-500">// Engine log initialized. Awaiting next tick/bar evaluation...</div>
            ) : (
              <div className="space-y-1">
                {engineLog.map((l, i) => (
                  <div key={i} className="flex items-start gap-2 border-b border-ink-800/30 pb-0.5">
                    <span className="text-fg-500 shrink-0">
                      [{typeof l.ts === 'number' ? new Date(l.ts).toLocaleTimeString() : String(l.ts || '')}]
                    </span>
                    <span
                      className={clsx(
                        'font-semibold uppercase shrink-0',
                        l.type === 'ENTRY' ? 'text-bull-400' : l.type === 'EXIT' ? 'text-gold-400' : 'text-fg-300',
                      )}
                    >
                      {l.type || 'SIGNAL'}:
                    </span>
                    <span className="text-fg-200">{l.reason || JSON.stringify(l)}</span>
                    {l.price && <span className="ml-auto text-fg-400 font-bold">{fmtPrice(l.price)}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}


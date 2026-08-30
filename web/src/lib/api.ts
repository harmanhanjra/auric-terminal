import type {
  Account,
  BacktestResult,
  CandleResponse,
  EngineStatus,
  Health,
  JournalResponse,
  OrderRequest,
  OrderResult,
  PositionsResponse,
  Quote,
  StrategiesResponse,
  KillResult,
  Candle,
  KronosStatus,
  KronosForecast,
  KronosDataset,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export interface SymbolSummary {
  symbol: string
  category: string
  status: string
}

export const api = {
  health: () => request<Health>('/api/health'),
  quote: () => request<Quote>('/api/quote'),
  strategies: () => request<StrategiesResponse>('/api/strategies'),
  account: () => request<Account>('/api/account'),
  symbols: () => request<{ symbols: SymbolSummary[] }>('/api/symbols'),
  symbolQuote: (symbol: string) =>
    request<Quote>(`/api/symbols/${encodeURIComponent(symbol)}/quote`).catch(() => null as unknown as Quote),
  positions: () => request<PositionsResponse>('/api/positions'),
  journal: (limit = 100) => request<JournalResponse>(`/api/journal?limit=${limit}`),
  engine: () => request<EngineStatus>('/api/engine'),
  candles: (interval: string, outputsize = 300, symbol?: string) =>
    request<CandleResponse>(
      `/api/candles?interval=${interval}&outputsize=${outputsize}&symbol=${symbol ?? 'XAUUSD'}`,
    ),
  backtest: (payload: {
    candles: Candle[]
    strategy: string
    params: Record<string, unknown>
    initial: number
    risk_pct: number
    sizer: string
    spread: number
  }) => request<BacktestResult>('/api/backtest', { method: 'POST', body: JSON.stringify(payload) }),
  order: (payload: OrderRequest) =>
    request<OrderResult>('/api/orders', { method: 'POST', body: JSON.stringify(payload) }),
  kill: (mode: 'paper' | 'live') => request<KillResult>(`/api/kill?mode=${mode}`, { method: 'POST' }),
  kronosStatus: () => request<KronosStatus>('/api/kronos/status'),
  kronosDatasets: () => request<{ datasets: KronosDataset[] }>('/api/kronos/datasets'),
  kronosForecast: (payload: {
    dataset: string
    lookback: number
    pred_len: number
    model: string
    T: number
    top_p: number
    sample_count: number
  }) => request<KronosForecast>('/api/kronos/forecast', { method: 'POST', body: JSON.stringify(payload) }),
}

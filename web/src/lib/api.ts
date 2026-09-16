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

export const LIVE_KEY_STORAGE = 'auric.liveKey'

export function getLiveKey(): string {
  try {
    return localStorage.getItem(LIVE_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setLiveKey(key: string): void {
  try {
    if (key) localStorage.setItem(LIVE_KEY_STORAGE, key)
    else localStorage.removeItem(LIVE_KEY_STORAGE)
  } catch {
    /* ignore */
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const liveKey = getLiveKey()
  // Server fail-closes live mutations without a matching X-Auric-Key.
  if (liveKey) headers['X-Auric-Key'] = liveKey
  const res = await fetch(path, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
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
  order: (payload: OrderRequest & { symbol?: string }) =>
    request<OrderResult>('/api/orders', { method: 'POST', body: JSON.stringify(payload) }),
  engineStart: () => request<EngineStatus>('/api/engine/start', { method: 'POST' }),
  engineStop: () => request<EngineStatus>('/api/engine/stop', { method: 'POST' }),
  symbolStart: (symbol: string) =>
    request<EngineStatus>(`/api/symbols/${encodeURIComponent(symbol)}/start`, { method: 'POST' }),
  symbolStop: (symbol: string) =>
    request<EngineStatus>(`/api/symbols/${encodeURIComponent(symbol)}/stop`, { method: 'POST' }),
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

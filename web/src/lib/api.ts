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
  RiskPreview,
  LoginResult,
  ProductionStatus,
  ReadinessStatus,
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
export const SESSION_STORAGE = 'auric.session.v1'

export function getLiveKey(): string {
  try {
    return sessionStorage.getItem(LIVE_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setLiveKey(key: string): void {
  try {
    if (key) sessionStorage.setItem(LIVE_KEY_STORAGE, key)
    else sessionStorage.removeItem(LIVE_KEY_STORAGE)
  } catch {
    /* ignore */
  }
}

export function getSessionToken(): string {
  try {
    return sessionStorage.getItem(SESSION_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setSessionToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(SESSION_STORAGE, token)
    else sessionStorage.removeItem(SESSION_STORAGE)
  } catch {
    /* ignore */
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const liveKey = getLiveKey()
  const session = getSessionToken()
  // Operator identity and live-execution authorization are intentionally separate.
  if (session) headers.Authorization = `Bearer ${session}`
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
  depth: (symbol: string) => request<{available: boolean; levels: {side: string; price: number; volume: number}[]}>(`/api/depth/${encodeURIComponent(symbol)}`),
  health: () => request<Health>('/api/health'),
  login: (username: string, password: string) =>
    request<LoginResult>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => request<{ authenticated: boolean; claims?: Record<string, unknown> }>('/api/auth/me'),
  readiness: () => request<ReadinessStatus>('/api/readiness'),
  productionStatus: () => request<ProductionStatus>('/api/production/status'),
  reconciliation: () => request<ProductionStatus['reconciliation']>('/api/reconciliation'),
  quote: () => request<Quote>('/api/quote'),
  strategies: () => request<StrategiesResponse>('/api/strategies'),
  account: () => request<Account>('/api/account'),
  symbols: () => request<{ symbols: SymbolSummary[] }>('/api/symbols'),
  symbolQuote: (symbol: string) =>
    request<Quote>(`/api/symbols/${encodeURIComponent(symbol)}/quote`).catch(() => null as unknown as Quote),
  positions: (mode: 'paper' | 'live' | 'all' = 'all', symbol?: string) => {
    const params = new URLSearchParams({ mode })
    if (symbol) params.set('symbol', symbol)
    return request<PositionsResponse>(`/api/positions?${params.toString()}`)
  },
  journal: (limit = 100) => request<JournalResponse>(`/api/journal?limit=${limit}`),
  engine: () => request<EngineStatus>('/api/engine'),
  symbolEngine: (symbol: string) =>
    request<EngineStatus>(`/api/symbols/${encodeURIComponent(symbol)}`),
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
  riskPreview: (payload: {
    symbol: string
    side: 'buy' | 'sell'
    entry: number
    stop: number
    target?: number | null
    risk_pct?: number
    risk_amount?: number | null
  }) => request<RiskPreview>('/api/risk/preview', { method: 'POST', body: JSON.stringify(payload) }),
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

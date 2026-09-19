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
  ProductionStatus,
  Readiness,
  NewsEvent,
  ExecutionStage,
  RiskPolicy,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export const LIVE_KEY_STORAGE = 'auric.liveKey.v3'
export const AUTH_KEY_STORAGE = 'auric.authKey.v3'

function getSessionSecret(key: string): string {
  try {
    return sessionStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function setSessionSecret(key: string, value: string): void {
  try {
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
    window.dispatchEvent(new Event('auric-credentials-changed'))
  } catch {
    /* ignore */
  }
}

export const getLiveKey = () => getSessionSecret(LIVE_KEY_STORAGE)
export const setLiveKey = (key: string) => setSessionSecret(LIVE_KEY_STORAGE, key)
export const getAuthKey = () => getSessionSecret(AUTH_KEY_STORAGE)
export const setAuthKey = (key: string) => setSessionSecret(AUTH_KEY_STORAGE, key)

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const liveKey = getLiveKey()
  const authKey = getAuthKey()
  // RBAC credential and high-risk live-execution credential are intentionally separate.
  if (authKey) headers['X-Auric-Auth'] = authKey
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
  readiness: () => request<Readiness>('/api/readiness'),
  systemStatus: () => request<ProductionStatus>('/api/system/status'),
  setExecutionStage: (stage: ExecutionStage) =>
    request<{ ok: boolean; executionStage: ExecutionStage }>('/api/system/stage', {
      method: 'POST',
      body: JSON.stringify({ stage }),
    }),
  resumeSystem: () => request<{ ok: boolean }>('/api/system/resume', { method: 'POST' }),
  reconcile: () => request<Record<string, unknown>>('/api/reconcile', { method: 'POST' }),
  newsEvents: () => request<{ events: NewsEvent[] }>('/api/news/events'),
  addNewsEvent: (payload: Omit<NewsEvent, 'id' | 'enabled'>) =>
    request<{ ok: boolean; id: number }>('/api/news/events', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  disableNewsEvent: (id: number) =>
    request<{ ok: boolean }>(`/api/news/events/${id}/disable`, { method: 'POST' }),
  riskPolicy: () => request<RiskPolicy>('/api/risk/policy'),
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
  closePosition: (ticket: number, mode: 'paper' | 'live', lots?: number) =>
    request<{ ok: boolean }>(`/api/positions/${ticket}/close`, {
      method: 'POST',
      body: JSON.stringify({ mode, lots: lots ?? null }),
    }),
  protectPosition: (
    ticket: number,
    mode: 'paper' | 'live',
    payload: { sl?: number | null; tp?: number | null; breakeven?: boolean },
  ) => request<{ ok: boolean }>(`/api/positions/${ticket}/protect`, {
    method: 'POST',
    body: JSON.stringify({ mode, ...payload }),
  }),
  cancelPending: (ticket: number, mode: 'paper' | 'live') =>
    request<{ ok: boolean }>(`/api/pending/${ticket}?mode=${mode}`, { method: 'DELETE' }),
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

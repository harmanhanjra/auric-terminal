export interface Quote {
  symbol: string
  bid: number
  ask: number
  price: number
  spread: number
  source: string
  timestamp: number
  error?: string
}

export interface Health {
  ok: boolean
  source: string
  liveTrading: boolean
  symbol: string
  timestamp: number
}

export interface Candle {
  time?: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface CandleResponse {
  symbol: string
  interval: string
  source: string
  values: Candle[]
}

export interface Strategy {
  id: string
  name: string
  category: string
}

export interface StrategiesResponse {
  strategies: Strategy[]
  positionSizing: string[]
}

export interface Account {
  connected: boolean
  source?: string
  login?: number
  balance?: number
  equity?: number
  margin?: number
  freeMargin?: number
  marginLevel?: number
  currency?: string
}

export interface Position {
  ticket?: number
  symbol: string
  side: 'buy' | 'sell'
  lots: number
  entry: number
  market: number
  sl?: number
  tp?: number
  pnl: number
}

export interface PositionsResponse {
  positions: Position[]
}

export interface JournalEntry {
  id?: number
  ts: string | number
  mode: string
  side: string
  lots: number
  entry?: number
  pnl?: number
  strategy?: string
  reason?: string
}

export interface JournalResponse {
  entries: JournalEntry[]
}

export interface EngineSignal {
  side?: number
  reason?: string
  bar?: number
}

export interface EngineConfig {
  trail_atr?: number
  confirm_min?: number
  pyramid_frac?: number
  max_pyramid?: number
}

export interface EngineRisk {
  halted: boolean
  realized: number
  dailyLoss: number
}

export interface EngineLogEntry {
  ts?: string | number
  type?: string
  side?: number
  reason?: string
  reasons?: string[]
  lots?: number
  price?: number
  sl?: number
  bar?: number
  ticket?: number
}

export interface EngineStatus {
  running: boolean
  enabled: boolean
  strategy: string
  timeframe: string
  status: string
  lastBar?: number
  signal?: EngineSignal
  error?: string
  trades: number
  log: EngineLogEntry[]
  pyramids: number
  config: EngineConfig
  risk: EngineRisk
}

export interface BacktestMetrics {
  net_pnl: number
  max_drawdown_pct: number
  win_rate: number
  profit_factor: number
  sharpe: number
  trades: number
}

export interface BacktestResult {
  metrics: BacktestMetrics
  equity_curve: number[]
  [key: string]: unknown
}

export interface OrderResult {
  accepted: boolean
  mode: 'paper' | 'live'
  clientOrderId?: string
  ticket?: number
  deal?: number
  fillPrice?: number
  source?: string
}

export interface KillResult {
  ok: boolean
  mode: 'paper' | 'live'
  closed: number
  cancelled: number
  halted: boolean
}

export interface OrderRequest {
  side: 'buy' | 'sell'
  lots: number
  stop_loss?: number | null
  take_profit?: number | null
  mode: 'paper' | 'live'
  client_order_id: string
}

export interface KronosDataset {
  name: string
  path: string
  size: number
}

export interface KronosStatus {
  ok: boolean
  reason?: string
  datasets: KronosDataset[]
}

export interface KronosPoint {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}

export interface KronosForecast {
  historical: KronosPoint[]
  forecast: KronosPoint[]
  metadata: {
    model: string
    lookback: number
    pred_len: number
    last_close: number
    forecast_close: number
    pct_change: number
    rows: number
  }
}

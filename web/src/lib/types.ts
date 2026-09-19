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

export type ExecutionStage = 'shadow' | 'paper' | 'assisted' | 'auto'

export interface Health {
  ok: boolean
  version?: string
  source: string
  liveTrading: boolean
  autoLiveTrading?: boolean
  executionStage?: ExecutionStage
  halted?: boolean
  symbol: string
  timestamp: number
}

export interface RiskPolicy {
  maxOpenPositions: number
  maxTotalLots: number
  maxSymbolLots: number
  minMarginLevelPct: number
  maxMarginUsagePct: number
  maxRiskPerTradePct: number
}

export interface ProductionStatus {
  authRequired: boolean
  configuredPrincipals: number
  executionStage: ExecutionStage
  circuit: {
    halted: boolean
    reason: string
    haltedAt: number
  }
  newsGuard: {
    enabled: boolean
    minImpact: string
  }
  riskPolicy: RiskPolicy
  lastReconciliation?: {
    id: number
    ts: number
    status: string
    summary: Record<string, unknown>
  } | null
  version?: string
  mt5Connected?: boolean
  manualLiveEnabled?: boolean
  autoLiveEnabled?: boolean
  trackedSymbols?: string[]
}

export interface Readiness {
  ready: boolean
  checks: Record<string, boolean>
  source?: string
  production: ProductionStatus
  timestamp: number
}

export interface NewsEvent {
  id: number
  title: string
  impact: 'low' | 'medium' | 'high'
  start_ms: number
  end_ms: number
  symbols: string[]
  source: string
  enabled: number
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
  mode?: 'paper' | 'live'
}

export interface PositionsResponse {
  positions: Position[]
}

export interface PendingOrder {
  ticket: number
  symbol: string
  side?: 'buy' | 'sell'
  lots: number
  entry: number
  sl?: number
  tp?: number
  mode: 'paper' | 'live'
  orderType?: 'limit' | 'stop'
}

export interface PendingOrdersResponse {
  orders: PendingOrder[]
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
  risk_pct?: number
  atr_stop?: number
  rr?: number
  trail_atr?: number
  confirm_min?: number
  pyramid_frac?: number
  max_pyramid?: number
  autoLive?: boolean
}

export interface EngineRisk {
  halted: boolean
  realized: number
  dailyLoss: number
  maxSpreadPoints?: number
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
  manualLiveEnabled?: boolean
  autoLiveEnabled?: boolean
  production?: {
    executionStage: ExecutionStage
    globalHalt: boolean
    liveGate: string
  }
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
  status?: 'filled' | 'pending'
  mode: 'paper' | 'live'
  clientOrderId?: string
  ticket?: number
  deal?: number
  fillPrice?: number | null
  entryPrice?: number
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
  order_type: 'market' | 'limit' | 'stop'
  entry_price?: number | null
  stop_loss?: number | null
  take_profit?: number | null
  mode: 'paper' | 'live'
  client_order_id: string
}

export interface RiskPreview {
  symbol: string
  equity: number
  lots: number
  riskUsd: number
  rewardUsd?: number | null
  rr?: number | null
  margin?: number | null
  spec: {
    symbol: string
    digits: number
    point: number
    tick_size: number
    tick_value: number
    contract_size: number
    volume_min: number
    volume_max: number
    volume_step: number
  }
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

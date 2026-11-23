export type Session = {
  provider: string
  id: string
  agentId: string | null
  processId: number | null
  processAlive: boolean | null
  heartbeatAgeSeconds: number | null
  stale: boolean
  title: string
  state: string
  blocker: string | null
  observedAt: string | null
  source: string
}

export type Message = {
  id: string
  role: 'user' | 'assistant'
  text: string
}

export type Agent = {
  id: string
  name: string
  role: string | null
  floor: string | null
  provider: string | null
  status: string
  processVerified: boolean
  activity: string | null
  processId: number | null
  lastActiveSecAgo: number | null
}

export type FleetTerminal = {
  id: string
  name: string
  kind: 'agent_session' | 'shell'
  provider: string | null
  status: string | null
  pid: number | null
  processAlive: boolean | null
  command: string | null
  cwd: string | null
  tty: string | null
  observedAt: string | null
}

export type FleetState = {
  agents: Agent[]
  sessions: Session[]
  terminals: FleetTerminal[]
  observedAt: string | null
  stale: boolean
}

export type Fundamentals = {
  symbol: string
  name: string
  sector: string
  industry: string | null
  price: number | null
  marketCap: number | null
  peRatio: number | null
  pbRatio: number | null
  evEbitda: number | null
  roe: number | null
  profitMargin: number | null
  debtToEquity: number | null
  currentRatio: number | null
  revenueGrowth: number | null
  earningsGrowth: number | null
  dividendYield: number | null
  valuationFlag: string | null
  leverageFlag: string | null
  liquidityFlag: string | null
  momentumFlag: string | null
  score: number
  scoreCoverage: number
  updatedAt: string
}

export type PortfolioPosition = {
  symbol: string
  side: 'LONG' | 'SHORT'
  quantity: number
  avgEntryPrice: number
  markPrice: number
  unrealizedPnl: number
  unrealizedPnlPct: number
  realizedPnl: number
  notional: number
}

export type PortfolioSnapshot = {
  available: boolean
  broker: string | null
  currency: string
  cash: number | null
  marketValue: number | null
  equity: number | null
  realizedPnl: number | null
  unrealizedPnl: number | null
  totalPnl: number | null
  peakEquity: number | null
  maxDrawdown: number | null
  drawdownPercent: number | null
  positions: PortfolioPosition[]
  asOf: string | null
  source: string
  stale: boolean
  ageMinutes: number | null
}

export type PerformanceRun = {
  runId: string
  startedAt: string | null
  finishedAt: string | null
  status: 'success' | 'error'
  paperOnly: boolean
  dryRun: boolean
  equity: number | null
  totalPnl: number | null
  filledOrders: number
  rejectedOrders: number
  errors: string[]
}

export type PerformanceSnapshot = {
  available: boolean
  source: string
  runs: PerformanceRun[]
  latestEquity: number | null
  bestEquity: number | null
  worstEquity: number | null
}

export type RiskAlert = {
  rule: string
  symbol: string
  severity: 'high' | 'medium' | 'low'
  kind: 'active_condition' | 'transition'
  details: Record<string, string>
  detectedAt: string
  sourceAnalyzedAt: string | null
}

export type RiskSnapshot = {
  readOnly: boolean
  paperOnly: boolean
  portfolio: PortfolioSnapshot
  alerts: RiskAlert[]
  performance: PerformanceSnapshot
  checkedAt: string
}

export type SettingsSnapshot = {
  readOnly: boolean
  paperOnly: boolean
  killSwitch: 'locked'
  allowedOperations: string[]
  api: {
    host: string
    port: number
  }
  sources: {
    sessions: string
    fleet: string
    terminals: string
    portfolioDatabase: string
    portfolioFallback: string
    fundamentals: string
    alerts: string
  }
}

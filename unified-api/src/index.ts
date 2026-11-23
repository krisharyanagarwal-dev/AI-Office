import Fastify from 'fastify'
import websocket from '@fastify/websocket'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import http from 'node:http'
import { execSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'
import { DatabaseSync } from 'node:sqlite'

type SessionState = 'idle' | 'busy' | 'blocked' | 'unknown'

interface Session {
  provider: string
  id: string
  agentId: string | null
  processId: number | null
  processAlive: boolean | null
  heartbeatAgeSeconds: number | null
  stale: boolean
  title: string
  state: SessionState
  blocker: string | null
  observedAt: string | null
  source: 'live'
}

interface FleetAgent {
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

interface FleetTerminal {
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

interface FleetState {
  agents: FleetAgent[]
  sessions: Session[]
  terminals: FleetTerminal[]
  observedAt: string | null
  stale: boolean
}

interface Fundamental {
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
  updatedAt: string | null
}

interface ServiceStatus {
  name: string
  port: number
  path: string
  status: 'healthy' | 'degraded' | 'down'
  lastCheck: string
  responseTimeMs: number
}

interface LaunchdJob {
  label: string
  status: 'running' | 'stopped' | 'error'
  pid: number | null
  lastExitCode: number | null
  startInterval: number | null
}

interface ResourceMetrics {
  cpuPercent: number
  memoryPercent: number
  diskPercent: number
  networkInMbps: number | null
  networkOutMbps: number | null
  timestamp: string
}

interface PortfolioPosition {
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

interface PortfolioSnapshot {
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

interface PerformanceRun {
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

interface PerformanceSnapshot {
  available: boolean
  source: string
  runs: PerformanceRun[]
  latestEquity: number | null
  bestEquity: number | null
  worstEquity: number | null
}

interface RiskAlert {
  id: string
  rule: string
  symbol: string
  severity: 'high' | 'medium' | 'low'
  kind: 'active_condition' | 'transition'
  details: Record<string, string>
  detectedAt: string
  sourceAnalyzedAt: string | null
}

const HIVE_SESSIONS_PATH = '/Users/aryanagarwal/openalice-fleet/hive/sessions.json'
const HIVE_FLEET_PATH = '/Users/aryanagarwal/openalice-fleet/hive/fleet.json'
const HIVE_TERMINALS_PATH = '/Users/aryanagarwal/openalice-fleet/hive/terminals.json'
const LAUNCH_AGENTS_DIR = path.join(os.homedir(), 'Library', 'LaunchAgents')
const REPORTS_DIR = '/Users/aryanagarwal/reports'
const LIVE_METRICS_PATH = '/Users/aryanagarwal/.openclaw/stocks_metrics.json'
const PORTFOLIO_PATH = '/Users/aryanagarwal/.openclaw/all_in_one_portfolio.json'
const STATE_DATABASE_PATH = '/Users/aryanagarwal/AI-Office/data/all_in_one_state.db'
const ALERT_STATE_PATH = '/Users/aryanagarwal/.openclaw/fundamentals_alert_state.json'

// Loopback services that make up the trading stack, each with a real route to probe.
const SERVICE_REGISTRY: Array<{ name: string; port: number; probePath: string }> = [
  { name: 'Unified API', port: 4749, probePath: '/api/health' },
  { name: 'Office HUD', port: 4747, probePath: '/api/health' },
  { name: 'OpenClaw Control', port: 18789, probePath: '/' },
  { name: 'Fleet Console', port: 4790, probePath: '/' },
  { name: 'Session Control', port: 3000, probePath: '/' },
  { name: 'OpenAlice Control', port: 4950, probePath: '/' },
]

type RawRecord = Record<string, unknown>

interface FundamentalsDataset {
  rows: Fundamental[]
  bySymbol: Map<string, Fundamental>
}

interface SummarySelection {
  file: string
  records: RawRecord[]
  analyzedAtMs: number
}

const FUNDAMENTALS_CACHE_TTL_MS = 60_000
const SESSION_STALE_AFTER_SECONDS = 15 * 60

let fundamentalsCache: { builtAtMs: number; dataset: FundamentalsDataset } | null = null

function parseCsvRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false

  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i++
        } else {
          inQuotes = false
        }
      } else {
        field += char
      }
      continue
    }
    if (char === '"') {
      inQuotes = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else if (char !== '\r') {
      field += char
    }
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

function parseCsv(text: string): RawRecord[] {
  const rows = parseCsvRows(text)
  if (rows.length === 0) return []
  const header = rows[0].map((name) => name.trim())
  const records: RawRecord[] = []

  for (let i = 1; i < rows.length; i++) {
    const values = rows[i]
    if (values.length === 1 && values[0].trim() === '') continue
    const record: RawRecord = {}
    for (let column = 0; column < header.length; column++) {
      record[header[column]] = values[column] ?? ''
    }
    records.push(record)
  }
  return records
}

function firstDefined(...values: unknown[]): unknown {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const cleaned = value.trim().replace(/,/g, '')
  if (!cleaned || cleaned === '—' || cleaned === 'N/A') return null
  const parsed = Number(cleaned)
  return Number.isFinite(parsed) ? parsed : null
}

function toText(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed || trimmed === '—' || trimmed === 'N/A') return null
    return trimmed
  }
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}

function symbolAliases(symbol: string): string[] {
  const sym = symbol.trim()
  const aliases = [sym]
  if (sym.endsWith('.NS')) {
    aliases.push(sym.slice(0, -3))
  } else if (sym.endsWith('-USD')) {
    const base = sym.slice(0, -4)
    aliases.push(`${base}/USD`, `${base}USD`, `${base}USDT`, `${base}/USDT`, base)
  } else if (sym.includes('-')) {
    aliases.push(sym.replace('-', '.'))
  }
  return aliases
}

function selectSummaryCsv(reportsDir: string): SummarySelection | null {
  let files: string[]
  try {
    files = fs.readdirSync(reportsDir)
  } catch {
    return null
  }

  let best: SummarySelection | null = null
  for (const file of files) {
    if (!file.startsWith('all_stocks_summary_') || !file.endsWith('.csv')) continue
    const full = path.join(reportsDir, file)
    try {
      const text = fs.readFileSync(full, 'utf8')
      const table = parseCsvRows(text)
      const header = table[0]?.map((name) => name.trim()) ?? []
      if (!header.includes('symbol') || !header.includes('analyzed_at')) continue
      const records = parseCsv(text).flatMap((record) => {
        const symbol = toText(record.symbol)
        const analyzedAt = normalizeIsoDate(record.analyzed_at)
        return symbol && analyzedAt ? [{ ...record, analyzed_at: analyzedAt }] : []
      })
      if (records.length === 0) continue
      const analyzedAtMs = Math.max(...records.map((record) => new Date(record.analyzed_at as string).getTime()))
      if (!best || analyzedAtMs > best.analyzedAtMs || (analyzedAtMs === best.analyzedAtMs && full > best.file)) {
        best = { file: full, records, analyzedAtMs }
      }
    } catch {
      continue
    }
  }
  return best
}

function loadDetailRecords(reportsDir: string): Map<string, RawRecord> {
  const latest = new Map<string, { analyzedAtMs: number; record: RawRecord }>()

  let files: string[]
  try {
    files = fs.readdirSync(reportsDir)
  } catch {
    return new Map()
  }

  for (const file of files) {
    if (!file.endsWith('.json') || file.startsWith('all_stocks_summary')) continue
    const full = path.join(reportsDir, file)
    try {
      const record = JSON.parse(fs.readFileSync(full, 'utf8')) as RawRecord
      const analyzedAt = normalizeIsoDate(record.analyzed_at)
      const symbol = toText(record.symbol)
      if (!symbol || !analyzedAt) continue
      const analyzedAtMs = new Date(analyzedAt).getTime()
      const existing = latest.get(symbol)
      if (!existing || analyzedAtMs > existing.analyzedAtMs) latest.set(symbol, { analyzedAtMs, record })
    } catch {
      continue
    }
  }

  const details = new Map<string, RawRecord>()
  for (const [symbol, entry] of latest) details.set(symbol, entry.record)
  return details
}

function loadLiveAliases(metricsPath: string): Record<string, RawRecord> {
  try {
    if (!fs.existsSync(metricsPath)) return {}
    const payload = JSON.parse(fs.readFileSync(metricsPath, 'utf8')) as RawRecord
    const aliases = payload.fundamentals_by_symbol
    return aliases && typeof aliases === 'object' && !Array.isArray(aliases)
      ? (aliases as Record<string, RawRecord>)
      : {}
  } catch {
    return {}
  }
}

function ramp(value: number | null, zeroAt: number, fullAt: number): number | null {
  if (value === null) return null
  const position = (value - zeroAt) / (fullAt - zeroAt)
  return Math.max(0, Math.min(100, position * 100))
}

function normalizeDebtToEquity(value: number | null, unit: string | null): number | null {
  if (value === null) return null
  if (unit === 'ratio') return value
  if (unit === 'percent') return value / 100
  if (unit !== null) return null
  // Legacy Yahoo values are percentages; computed totalDebt/totalEquity values are ratios.
  return Math.abs(value) > 10 ? value / 100 : value
}

function computeScore(metrics: {
  peRatio: number | null
  pbRatio: number | null
  roe: number | null
  profitMargin: number | null
  currentRatio: number | null
  debtToEquity: number | null
  revenueGrowth: number | null
  earningsGrowth: number | null
  pctFrom52wHigh: number | null
}): { score: number; coverage: number } {
  const groups: Array<{ weight: number; parts: Array<number | null> }> = [
    { weight: 30, parts: [ramp(metrics.peRatio, 60, 8), ramp(metrics.pbRatio, 8, 0.8)] },
    { weight: 22, parts: [ramp(metrics.roe, 0, 0.25), ramp(metrics.profitMargin, 0, 0.2)] },
    { weight: 23, parts: [ramp(metrics.currentRatio, 0.8, 2.5), ramp(metrics.debtToEquity, 1.5, 0.5)] },
    { weight: 20, parts: [ramp(metrics.revenueGrowth, -0.1, 0.25), ramp(metrics.earningsGrowth, -0.2, 0.25)] },
    { weight: 5, parts: [ramp(metrics.pctFrom52wHigh, -0.4, 0)] },
  ]

  let weighted = 0
  let weightUsed = 0
  let coverage = 0
  for (const group of groups) {
    const available = group.parts.filter((part): part is number => part !== null)
    if (available.length === 0) continue
    const groupScore = available.reduce((sum, part) => sum + part, 0) / available.length
    weighted += groupScore * group.weight
    weightUsed += group.weight
    coverage += group.weight * (available.length / group.parts.length)
  }

  if (weightUsed === 0) return { score: 50, coverage: 0 }
  return { score: Math.round(weighted / weightUsed), coverage: Number(coverage.toFixed(1)) }
}

function recordTime(record: RawRecord | null): number | null {
  const analyzedAt = normalizeIsoDate(record?.analyzed_at)
  return analyzedAt ? new Date(analyzedAt).getTime() : null
}

function newestRecordTime(...records: Array<RawRecord | null>): string | null {
  const timestamps = records.flatMap((record) => {
    const analyzedAt = normalizeIsoDate(record?.analyzed_at)
    return analyzedAt ? [new Date(analyzedAt).getTime()] : []
  })
  return timestamps.length > 0 ? new Date(Math.max(...timestamps)).toISOString() : null
}

function buildFundamental(
  symbol: string,
  csv: RawRecord | null,
  detail: RawRecord | null,
  live: RawRecord | null,
): Fundamental {
  const csvTime = recordTime(csv)
  const detailTime = recordTime(detail)
  const sources = detailTime !== null && (csvTime === null || detailTime > csvTime)
    ? [detail, csv]
    : [csv, detail]
  const values = (...keys: string[]) => firstDefined(...sources.flatMap((record) => keys.map((key) => record?.[key])))
  const metric = (...keys: string[]) => toNumber(values(...keys))
  const rawDebtToEquity = metric('debt_to_equity')
  const debtSource = sources.find((record) => toNumber(record?.debt_to_equity) !== null)
  const debtUnit = toText(debtSource?.debt_to_equity_unit)?.toLowerCase() ?? null
  const debtToEquity = normalizeDebtToEquity(rawDebtToEquity, debtUnit)
  const peRatio = metric('pe_ttm')
  const pbRatio = metric('pb')
  const roe = metric('roe')
  const profitMargin = metric('profit_margin')
  const currentRatio = metric('current_ratio')
  const revenueGrowth = metric('revenue_growth')
  const earningsGrowth = metric('earnings_growth')
  const pctFrom52wHigh = metric('pct_from_52w_high')
  const { score, coverage } = computeScore({
    peRatio,
    pbRatio,
    roe,
    profitMargin,
    currentRatio,
    debtToEquity,
    revenueGrowth,
    earningsGrowth,
    pctFrom52wHigh,
  })

  return {
    symbol,
    name: toText(firstDefined(live?.name, values('name'))) ?? symbol,
    sector: toText(values('sector', 'asset_class')) ?? 'Unclassified',
    industry: toText(values('industry')),
    price: toNumber(firstDefined(live?.price, values('price'))),
    marketCap: toNumber(firstDefined(live?.market_cap, values('market_cap'))),
    peRatio,
    pbRatio,
    evEbitda: metric('ev_ebitda'),
    roe,
    profitMargin,
    debtToEquity,
    currentRatio,
    revenueGrowth,
    earningsGrowth,
    dividendYield: metric('dividend_yield'),
    valuationFlag: toText(firstDefined(live?.valuation_flag, values('valuation_flag'))),
    leverageFlag: toText(firstDefined(live?.leverage_flag, values('leverage_flag'))),
    liquidityFlag: toText(firstDefined(live?.liquidity_flag, values('liquidity_flag'))),
    momentumFlag: toText(firstDefined(live?.momentum_flag, values('momentum_flag'))),
    score,
    scoreCoverage: coverage,
    updatedAt: newestRecordTime(csv, detail, live),
  }
}

function buildFundamentals(
  paths: { reportsDir?: string; liveMetricsPath?: string } = {},
): FundamentalsDataset {
  const rows: Fundamental[] = []
  const bySymbol = new Map<string, Fundamental>()
  const reportsDir = paths.reportsDir ?? REPORTS_DIR
  const details = loadDetailRecords(reportsDir)
  const liveAliases = loadLiveAliases(paths.liveMetricsPath ?? LIVE_METRICS_PATH)
  const summary = selectSummaryCsv(reportsDir)
  const csvRecords = summary?.records ?? []

  const liveByCanonical = new Map<string, RawRecord>()
  for (const entry of Object.values(liveAliases)) {
    const canonical = toText(entry.symbol)
    if (!canonical || liveByCanonical.has(canonical)) continue
    liveByCanonical.set(canonical, entry)
  }

  const seen = new Set<string>()
  for (const record of csvRecords) {
    const symbol = toText(record.symbol)
    if (!symbol) continue
    seen.add(symbol)
    const detail = details.get(symbol) ?? null
    const live = liveAliases[symbol] ?? liveAliases[symbol.toUpperCase()] ?? liveByCanonical.get(symbol) ?? null
    rows.push(buildFundamental(symbol, record, detail, live))
  }

  for (const [canonical, entry] of liveByCanonical) {
    if (seen.has(canonical)) continue
    const detail = details.get(canonical) ?? null
    rows.push(buildFundamental(canonical, null, detail, entry))
  }

  for (const row of rows) {
    bySymbol.set(row.symbol, row)
    for (const alias of symbolAliases(row.symbol)) {
      if (!bySymbol.has(alias)) bySymbol.set(alias, row)
      const upper = alias.toUpperCase()
      if (!bySymbol.has(upper)) bySymbol.set(upper, row)
    }
  }

  return { rows, bySymbol }
}

function getFundamentals(): FundamentalsDataset {
  const now = Date.now()
  if (fundamentalsCache && now - fundamentalsCache.builtAtMs < FUNDAMENTALS_CACHE_TTL_MS) {
    return fundamentalsCache.dataset
  }
  const dataset = buildFundamentals()
  fundamentalsCache = { builtAtMs: now, dataset }
  return dataset
}

function mapHiveState(status: string): SessionState {
  switch ((status || '').toUpperCase()) {
    case 'HEALTHY':
    case 'IDLE':
      return 'idle'
    case 'ACTIVE':
    case 'BUSY':
    case 'RUNNING':
      return 'busy'
    case 'BLOCKED':
    case 'WAITING':
      return 'blocked'
    default:
      return 'unknown'
  }
}

function loadSessions(
  paths: { sessionsPath?: string; now?: number } = {},
): Session[] {
  const sessionsPath = paths.sessionsPath ?? HIVE_SESSIONS_PATH
  const nowMs = paths.now ?? Date.now()
  if (!fs.existsSync(sessionsPath)) {
    throw new Error('Session hive is unavailable')
  }

  let hiveData: any
  try {
    hiveData = JSON.parse(fs.readFileSync(sessionsPath, 'utf8'))
  } catch (error) {
    console.warn('Could not load sessions from hive:', error)
    throw new Error('Session hive could not be read')
  }

  const hiveSessions: any[] = Array.isArray(hiveData) ? hiveData : hiveData.sessions || []
  return hiveSessions.flatMap((hiveSession) => {
    const id: string = hiveSession.session_id || hiveSession.id || ''
    if (!id) return []
    const heartbeat = normalizeIsoDate(hiveSession.last_heartbeat ?? hiveSession.updated_at)
    const heartbeatMs = heartbeat ? new Date(heartbeat).getTime() : null
    const heartbeatAgeSeconds = heartbeatMs === null
      ? null
      : Math.max(0, Math.round((nowMs - heartbeatMs) / 1000))
    const processAlive = typeof hiveSession.process_alive === 'boolean' ? hiveSession.process_alive : null
    return [{
      provider: hiveSession.provider || 'unknown',
      id,
      agentId: toText(hiveSession.agent_id),
      processId: toNumber(hiveSession.process_id),
      processAlive,
      heartbeatAgeSeconds,
      stale: processAlive === false || heartbeatAgeSeconds === null || heartbeatAgeSeconds > SESSION_STALE_AFTER_SECONDS,
      title: hiveSession.current_task_id
        ? `${hiveSession.provider} · ${hiveSession.current_task_id}`
        : `${hiveSession.provider} · agent ${hiveSession.agent_id || 'unknown'}`,
      state: mapHiveState(hiveSession.status),
      blocker: null,
      observedAt: normalizeIsoDate(hiveSession.updated_at ?? hiveSession.last_heartbeat),
      source: 'live' as const,
    }]
  })
}

function readJsonRecord(filePath: string, label: string): RawRecord {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8')) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${label} is not a JSON object`)
    }
    return parsed as RawRecord
  } catch (error) {
    throw new Error(`${label} is unavailable`, { cause: error })
  }
}

function normalizeIsoDate(value: unknown): string | null {
  const raw = toText(value)
  if (!raw) return null
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

function loadFleet(
  sessions: Session[],
  paths: { fleetPath?: string; terminalsPath?: string } = {},
): FleetState {
  const fleetPath = paths.fleetPath ?? HIVE_FLEET_PATH
  const terminalsPath = paths.terminalsPath ?? HIVE_TERMINALS_PATH
  let fleetData: RawRecord
  let terminalData: RawRecord
  try {
    fleetData = readJsonRecord(fleetPath, 'Fleet artifact')
    terminalData = readJsonRecord(terminalsPath, 'Terminal artifact')
  } catch {
    throw new Error('Fleet artifacts are unavailable')
  }

  const rawAgents = Array.isArray(fleetData.agents) ? fleetData.agents : []
  const agents = rawAgents.flatMap((value): FleetAgent[] => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return []
    const agent = value as RawRecord
    const id = toText(agent.id)
    if (!id) return []
    return [{
      id,
      name: toText(agent.name) ?? id,
      role: toText(agent.role),
      floor: toText(agent.floor),
      provider: toText(agent.provider),
      status: toText(agent.status) ?? 'unknown',
      processVerified: agent.processVerified === true,
      activity: toText(agent.activity),
      processId: toNumber(agent.processId ?? (agent.evidence as RawRecord | undefined)?.processId),
      lastActiveSecAgo: toNumber(agent.lastActiveSecAgo ?? (agent.evidence as RawRecord | undefined)?.lastActiveSecAgo),
    }]
  })

  const observedAt = normalizeIsoDate(terminalData.collected_at)
  const terminals: FleetTerminal[] = []
  const agentSessions = Array.isArray(terminalData.agent_sessions) ? terminalData.agent_sessions : []
  for (const value of agentSessions) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue
    const session = value as RawRecord
    const sessionId = toText(session.session_id)
    if (!sessionId) continue
    const provider = toText(session.provider)
    terminals.push({
      id: `session:${sessionId}`,
      name: sessionId,
      kind: 'agent_session',
      provider,
      status: toText(session.status),
      pid: toNumber(session.process_id),
      processAlive: typeof session.process_alive === 'boolean' ? session.process_alive : null,
      command: toText(session.evidence && (session.evidence as RawRecord).command),
      cwd: toText(session.cwd),
      tty: toText(session.evidence && (session.evidence as RawRecord).tty),
      observedAt,
    })
  }

  const shellTerminals = Array.isArray(terminalData.shell_terminals) ? terminalData.shell_terminals : []
  for (const value of shellTerminals) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue
    const shell = value as RawRecord
    const pid = toNumber(shell.pid)
    if (pid === null) continue
    terminals.push({
      id: `shell:${pid}`,
      name: toText(shell.name) ?? toText(shell.command) ?? `shell:${pid}`,
      kind: 'shell',
      provider: null,
      status: toText(shell.status),
      pid,
      processAlive: null,
      command: toText(shell.command),
      cwd: toText(shell.cwd),
      tty: toText(shell.tty),
      observedAt,
    })
  }

  const observedAtMs = observedAt ? new Date(observedAt).getTime() : null
  const ageMinutes = observedAtMs === null ? null : Math.max(0, Math.round((Date.now() - observedAtMs) / 60000))

  return {
    agents,
    sessions,
    terminals,
    observedAt,
    stale: ageMinutes === null || ageMinutes > 5,
  }
}

const PORTFOLIO_STALE_AFTER_MINUTES = 60

type SqliteStateRow = { key: string; value: string; timestamp: number; category: string }

function readSqliteState(databasePath: string): SqliteStateRow[] {
  const db = new DatabaseSync(databasePath, { readOnly: true })
  try {
    return db.prepare('SELECT key, value, timestamp, category FROM state').all() as unknown as SqliteStateRow[]
  } finally {
    db.close()
  }
}

function parseSqliteRecord(row: SqliteStateRow | undefined): RawRecord | null {
  if (!row) return null
  try {
    const parsed = JSON.parse(row.value) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as RawRecord : null
  } catch {
    return null
  }
}

function portfolioFromRecord(raw: RawRecord, source: string, nowMs: number): PortfolioSnapshot {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Portfolio snapshot is invalid')
  const requiredNumber = (key: string): number => {
    const value = toNumber(raw[key])
    if (value === null) throw new Error(`Portfolio ${key} is invalid`)
    return value
  }
  const rawPositions = raw.positions ?? {}
  if (!rawPositions || typeof rawPositions !== 'object' || Array.isArray(rawPositions)) {
    throw new Error('Portfolio positions are invalid')
  }
  const positions: PortfolioPosition[] = []

  for (const [symbol, value] of Object.entries(rawPositions as RawRecord)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Portfolio position ${symbol} is invalid`)
    const position = value as RawRecord
    const quantity = requiredPositionNumber(position, symbol, 'quantity')
    const avgEntryPrice = requiredPositionNumber(position, symbol, 'avg_entry_price')
    const markPrice = requiredPositionNumber(position, symbol, 'mark_price')
    const unrealizedPnl = requiredPositionNumber(position, symbol, 'unrealized_pnl')
    const realizedPnl = requiredPositionNumber(position, symbol, 'realized_pnl')
    const costBasis = Math.abs(quantity) * avgEntryPrice
    positions.push({
      symbol,
      side: quantity >= 0 ? 'LONG' : 'SHORT',
      quantity: Math.abs(quantity),
      avgEntryPrice,
      markPrice,
      unrealizedPnl,
      unrealizedPnlPct: costBasis > 0 ? (unrealizedPnl / costBasis) * 100 : 0,
      realizedPnl,
      notional: Math.abs(quantity) * markPrice,
    })
  }

  const currency = toText(raw.currency)?.toUpperCase() ?? 'USDT'
  if (!/^[A-Z0-9]{3,4}$/.test(currency)) throw new Error('Portfolio currency is invalid')
  const epochSeconds = toNumber(raw.timestamp)
  const asOfMs = epochSeconds !== null && epochSeconds > 0 ? epochSeconds * 1000 : null
  const ageMinutes = asOfMs ? Math.max(0, Math.round((nowMs - asOfMs) / 60000)) : null
  const peakEquity = toNumber(raw.peak_equity)
  const maxDrawdown = toNumber(raw.max_drawdown ?? raw.drawdown)

  return {
    available: true,
    broker: toText(raw.broker),
    currency,
    cash: requiredNumber('cash'),
    marketValue: requiredNumber('market_value'),
    equity: requiredNumber('equity'),
    realizedPnl: toNumber(raw.realized_pnl),
    unrealizedPnl: toNumber(raw.unrealized_pnl),
    totalPnl: requiredNumber('total_pnl'),
    peakEquity,
    maxDrawdown,
    drawdownPercent: peakEquity && peakEquity > 0 && maxDrawdown !== null
      ? (maxDrawdown / peakEquity) * 100
      : null,
    positions,
    asOf: asOfMs ? new Date(asOfMs).toISOString() : null,
    source,
    stale: ageMinutes === null || ageMinutes > PORTFOLIO_STALE_AFTER_MINUTES,
    ageMinutes,
  }
}

function requiredPositionNumber(position: RawRecord, symbol: string, key: string): number {
  const value = toNumber(position[key])
  if (value === null) throw new Error(`Portfolio position ${symbol} ${key} is invalid`)
  return value
}

function loadPortfolio(
  paths: { databasePath?: string; fallbackPath?: string; now?: number } = {},
): PortfolioSnapshot {
  const databasePath = paths.databasePath ?? STATE_DATABASE_PATH
  const fallbackPath = paths.fallbackPath ?? PORTFOLIO_PATH
  const nowMs = paths.now ?? Date.now()

  const unavailable = (source: string): PortfolioSnapshot => ({
    available: false,
    broker: null,
    currency: 'USDT',
    cash: null,
    marketValue: null,
    equity: null,
    realizedPnl: null,
    unrealizedPnl: null,
    totalPnl: null,
    peakEquity: null,
    maxDrawdown: null,
    drawdownPercent: null,
    positions: [],
    asOf: null,
    source,
    stale: true,
    ageMinutes: null,
  })

  try {
    const rows = readSqliteState(databasePath)
    const lastRun = parseSqliteRecord(rows.find((row) => row.key === 'last_run'))
    const snapshot = lastRun?.portfolio
    if (snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot)) {
      return portfolioFromRecord(snapshot as RawRecord, `sqlite:${databasePath}`, nowMs)
    }
  } catch {
    // The JSON snapshot remains an explicitly labeled fallback.
  }

  try {
    const raw = JSON.parse(fs.readFileSync(fallbackPath, 'utf8')) as RawRecord
    return portfolioFromRecord(raw, `json:${fallbackPath}`, nowMs)
  } catch {
    return unavailable(`sqlite:${databasePath};json:${fallbackPath}`)
  }
}

function loadPerformance(
  paths: { databasePath?: string } = {},
): PerformanceSnapshot {
  const databasePath = paths.databasePath ?? STATE_DATABASE_PATH
  const unavailable: PerformanceSnapshot = {
    available: false,
    source: `sqlite:${databasePath}`,
    runs: [],
    latestEquity: null,
    bestEquity: null,
    worstEquity: null,
  }

  try {
    const rows = readSqliteState(databasePath)
      .filter((row) => row.category === 'all_in_one_runs' || row.key.startsWith('run:'))
    const byRunId = new Map<string, { record: RawRecord; row: SqliteStateRow }>()
    for (const row of rows) {
      const record = parseSqliteRecord(row)
      if (!record) continue
      const runId = toText(record.run_id) ?? row.key.replace(/^run:/, '')
      const existing = byRunId.get(runId)
      if (!existing || row.timestamp > existing.row.timestamp) byRunId.set(runId, { record, row })
    }

    const runs = Array.from(byRunId.values()).map(({ record }): PerformanceRun => {
      const symbols = (record.symbols && typeof record.symbols === 'object' ? record.symbols : {}) as RawRecord
      const errors: string[] = []
      let filledOrders = 0
      let rejectedOrders = 0
      for (const value of Object.values(symbols)) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) continue
        const symbol = value as RawRecord
        const executed = Array.isArray(symbol.executed) ? symbol.executed : []
        const rejected = Array.isArray(symbol.rejected) ? symbol.rejected : []
        filledOrders += executed.filter((order) => order && typeof order === 'object' && (order as RawRecord).status === 'filled').length
        rejectedOrders += rejected.length
        if (Array.isArray(symbol.errors)) {
          errors.push(...symbol.errors.flatMap((error) => typeof error === 'string' ? [error] : []))
        }
      }
      if (Array.isArray(record.errors)) {
        errors.push(...record.errors.flatMap((error) => typeof error === 'string' ? [error] : []))
      }
      const portfolio = (record.portfolio && typeof record.portfolio === 'object' ? record.portfolio : {}) as RawRecord
      return {
        runId: toText(record.run_id) ?? '',
        startedAt: normalizeIsoDate(record.started_at),
        finishedAt: normalizeIsoDate(record.finished_at),
        status: errors.length > 0 ? 'error' : 'success',
        paperOnly: record.paper_only === true,
        dryRun: record.dry_run === true,
        equity: toNumber(portfolio.equity),
        totalPnl: toNumber(portfolio.total_pnl),
        filledOrders,
        rejectedOrders,
        errors,
      }
    }).sort((a, b) => {
      const aTime = a.startedAt ? new Date(a.startedAt).getTime() : 0
      const bTime = b.startedAt ? new Date(b.startedAt).getTime() : 0
      return bTime - aTime
    })

    const equities = runs.flatMap((run) => run.equity === null ? [] : [run.equity])
    return {
      available: true,
      source: `sqlite:${databasePath}`,
      runs,
      latestEquity: runs.find((run) => run.equity !== null)?.equity ?? null,
      bestEquity: equities.length > 0 ? Math.max(...equities) : null,
      worstEquity: equities.length > 0 ? Math.min(...equities) : null,
    }
  } catch {
    return unavailable
  }
}

type AlertCandidate = Omit<RiskAlert, 'id'>

function stableAlertId(alert: AlertCandidate): string {
  const details = Object.entries(alert.details).sort(([left], [right]) => left.localeCompare(right))
  return createHash('sha256')
    .update(JSON.stringify([alert.rule, alert.symbol, alert.kind, details]))
    .digest('hex')
    .slice(0, 16)
}

function loadRiskAlerts(
  paths: { metricsPath?: string; alertStatePath?: string; now?: number } = {},
): RiskAlert[] {
  const metricsPath = paths.metricsPath ?? LIVE_METRICS_PATH
  const alertStatePath = paths.alertStatePath ?? ALERT_STATE_PATH
  const nowMs = paths.now ?? Date.now()
  let payload: RawRecord
  try {
    const parsed = JSON.parse(fs.readFileSync(metricsPath, 'utf8')) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Metrics payload is invalid')
    payload = parsed as RawRecord
  } catch (error) {
    console.warn('Could not load fundamentals alerts:', error)
    throw new Error('Fundamentals alert source is unavailable')
  }

  const aliases = payload.fundamentals_by_symbol
  if (!aliases || typeof aliases !== 'object' || Array.isArray(aliases) || Object.keys(aliases).length === 0) {
    throw new Error('Fundamentals alert coverage is unavailable')
  }
  const aliasMap = aliases as Record<string, unknown>

  let previousSymbols: RawRecord = {}
  try {
    const state = JSON.parse(fs.readFileSync(alertStatePath, 'utf8')) as RawRecord
    previousSymbols = Object.fromEntries(Object.entries(state).filter(([key, value]) =>
      key !== 'last_run' && value && typeof value === 'object' && !Array.isArray(value)
    ))
  } catch {
    previousSymbols = {}
  }

  const canonical = new Map<string, RawRecord>()
  for (const value of Object.values(aliasMap)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue
    const facts = value as RawRecord
    const symbol = toText(facts.symbol)
    if (!symbol || canonical.has(symbol)) continue
    canonical.set(symbol, facts)
  }
  if (canonical.size === 0) throw new Error('Fundamentals alert coverage is unavailable')

  const detectedAt = new Date(nowMs).toISOString()
  const alerts: AlertCandidate[] = []

  for (const [symbol, facts] of canonical) {
    const previous = (previousSymbols[symbol] && typeof previousSymbols[symbol] === 'object'
      ? previousSymbols[symbol]
      : {}) as RawRecord
    const sourceAnalyzedAt = toText(facts.analyzed_at)
    const valuationFlag = toText(facts.valuation_flag)
    const leverageFlag = toText(facts.leverage_flag)
    const liquidityFlag = toText(facts.liquidity_flag)

    if (valuationFlag === 'Expensive' && leverageFlag === 'High') {
      alerts.push({
        rule: 'EXPENSIVE_HIGH_LEVERAGE',
        symbol,
        severity: 'high',
        kind: 'active_condition',
        details: { valuation_flag: valuationFlag, leverage_flag: leverageFlag },
        detectedAt,
        sourceAnalyzedAt,
      })
    }

    if (liquidityFlag === 'Tight') {
      alerts.push({
        rule: 'TIGHT_LIQUIDITY',
        symbol,
        severity: 'high',
        kind: 'active_condition',
        details: { liquidity_flag: liquidityFlag },
        detectedAt,
        sourceAnalyzedAt,
      })
    }

    const previousValuation = toText(previous.valuation_flag)
    if (valuationFlag === 'Expensive' && (previousValuation === 'Cheap' || previousValuation === 'Fair')) {
      alerts.push({
        rule: 'REGIME_CHANGE_TO_EXPENSIVE',
        symbol,
        severity: 'medium',
        kind: 'transition',
        details: { valuation_flag_old: previousValuation, valuation_flag_new: valuationFlag },
        detectedAt,
        sourceAnalyzedAt,
      })
    }

    for (const field of ['valuation_flag', 'leverage_flag', 'liquidity_flag', 'profitability_flag', 'roe_flag', 'momentum_flag']) {
      const previousValue = toText(previous[field])
      const currentValue = toText(facts[field])
      if (previousValue && previousValue !== 'N/A' && currentValue === null) {
        alerts.push({
          rule: 'UNEXPECTED_NA',
          symbol,
          severity: 'low',
          kind: 'transition',
          details: { field, old: previousValue, new: 'N/A' },
          detectedAt,
          sourceAnalyzedAt,
        })
      }
    }
  }

  return alerts.map((alert) => ({ ...alert, id: stableAlertId(alert) }))
}

function probeService(
  service: { name: string; port: number; probePath: string }
): Promise<ServiceStatus> {
  const started = Date.now()
  return new Promise((resolve) => {
    const req = http.get(
      { host: '127.0.0.1', port: service.port, path: service.probePath, timeout: 4000 },
      (res) => {
        res.resume()
        const responseTimeMs = Date.now() - started
        const code = res.statusCode || 0
        const status: ServiceStatus['status'] =
          code >= 200 && code < 400 ? 'healthy' : code >= 500 ? 'down' : 'degraded'
        resolve({
          name: service.name,
          port: service.port,
          path: service.probePath,
          status,
          lastCheck: new Date().toISOString(),
          responseTimeMs,
        })
      }
    )
    req.on('error', () => {
      resolve({
        name: service.name,
        port: service.port,
        path: service.probePath,
        status: 'down',
        lastCheck: new Date().toISOString(),
        responseTimeMs: Date.now() - started,
      })
    })
    req.on('timeout', () => {
      req.destroy()
      resolve({
        name: service.name,
        port: service.port,
        path: service.probePath,
        status: 'down',
        lastCheck: new Date().toISOString(),
        responseTimeMs: Date.now() - started,
      })
    })
  })
}

async function loadServiceHealth(): Promise<ServiceStatus[]> {
  const settled = await Promise.allSettled(SERVICE_REGISTRY.map(probeService))
  return settled.map((result, index) => {
    if (result.status === 'fulfilled') return result.value
    const service = SERVICE_REGISTRY[index]
    return {
      name: service.name,
      port: service.port,
      path: service.probePath,
      status: 'down' as const,
      lastCheck: new Date().toISOString(),
      responseTimeMs: 0,
    }
  })
}

function readStartInterval(label: string): number | null {
  const plistPath = path.join(LAUNCH_AGENTS_DIR, `${label}.plist`)
  try {
    if (!fs.existsSync(plistPath)) return null
    const content = fs.readFileSync(plistPath, 'utf8')
    const match = content.match(/<key>StartInterval<\/key>\s*<integer>(\d+)<\/integer>/)
    return match ? Number(match[1]) : null
  } catch {
    return null
  }
}

function loadLaunchdJobs(
  paths: { launchctlPath?: string } = {},
): LaunchdJob[] {
  const jobs: LaunchdJob[] = []

  let output = ''
  try {
    output = execSync(paths.launchctlPath ?? '/bin/launchctl', { encoding: 'utf8', timeout: 5000 })
  } catch (error) {
    throw new Error('launchctl launchd job source is unavailable', { cause: error })
  }

  for (const line of output.split('\n').slice(1)) {
    const [pidRaw, exitRaw, ...labelParts] = line.trim().split(/\s+/)
    const label = labelParts.join(' ')
    if (!label) continue
    if (!label.startsWith('com.aryan.') && !label.startsWith('dev.krisharyanagarwal.')) continue

    const pid = pidRaw && pidRaw !== '-' ? Number(pidRaw) : null
    const lastExitCode = exitRaw && exitRaw !== '-' ? Number(exitRaw) : null
    const status: LaunchdJob['status'] =
      pid !== null ? 'running' : lastExitCode !== null && lastExitCode !== 0 ? 'error' : 'stopped'

    jobs.push({
      label,
      status,
      pid,
      lastExitCode,
      startInterval: readStartInterval(label),
    })
  }

  return jobs.sort((a, b) => a.label.localeCompare(b.label))
}

function sampleCpuPercent(): number {
  const cpus = os.cpus()
  if (cpus.length === 0) return 0
  const before = cpus.map((cpu) => cpu.times)
  const buffer = new Int32Array(new SharedArrayBuffer(4))
  Atomics.wait(buffer, 0, 0, 200)
  const after = os.cpus().map((cpu) => cpu.times)

  let idleDelta = 0
  let totalDelta = 0
  for (let i = 0; i < before.length; i++) {
    const b = before[i]
    const a = after[i]
    const idle = a.idle - b.idle
    const total =
      a.user - b.user + a.nice - b.nice + a.sys - b.sys + a.irq - b.irq + idle
    idleDelta += idle
    totalDelta += total
  }

  if (totalDelta <= 0) return 0
  return Number((((totalDelta - idleDelta) / totalDelta) * 100).toFixed(1))
}

function sampleDiskPercent(): number {
  try {
    const output = execSync('/bin/df -k /', { encoding: 'utf8', timeout: 5000 })
    const lines = output.trim().split('\n')
    if (lines.length < 2) return 0
    const fields = lines[1].trim().split(/\s+/)
    const used = Number(fields[2])
    const available = Number(fields[3])
    const capacity = Number(fields[4])
    if (Number.isFinite(capacity) && capacity > 0) return capacity
    const total = used + available
    return total > 0 ? Number(((used / total) * 100).toFixed(1)) : 0
  } catch {
    return 0
  }
}

function parseNetworkBytes(output: string): { received: number; sent: number } | null {
  const lines = output.trim().split('\n')
  const header = (lines[0] ?? '').trim().split(/\s+/)
  const receivedIndex = header.indexOf('Ibytes')
  const sentIndex = header.indexOf('Obytes')
  if (receivedIndex === -1 || sentIndex === -1) return null

  for (const line of lines.slice(1)) {
    const fields = line.trim().split(/\s+/)
    if (fields[0] !== 'en0') continue
    const received = toNumber(fields[receivedIndex])
    const sent = toNumber(fields[sentIndex])
    if (received !== null && sent !== null && received >= 0 && sent >= 0) {
      return { received, sent }
    }
  }
  return null
}

function readNetworkBytes(): { received: number; sent: number } | null {
  try {
    const output = execSync('/usr/sbin/netstat -ib', { encoding: 'utf8', timeout: 5000 })
    return parseNetworkBytes(output)
  } catch {
    return null
  }
}

function sampleNetworkMbps(): { inMbps: number | null; outMbps: number | null } {
  const first = readNetworkBytes()
  const buffer = new Int32Array(new SharedArrayBuffer(4))
  Atomics.wait(buffer, 0, 0, 500)
  const second = readNetworkBytes()
  if (!first || !second) return { inMbps: null, outMbps: null }
  const seconds = 0.5
  const inMbps = Math.max(0, ((second.received - first.received) * 8) / seconds / 1_000_000)
  const outMbps = Math.max(0, ((second.sent - first.sent) * 8) / seconds / 1_000_000)
  return {
    inMbps: Number(inMbps.toFixed(2)),
    outMbps: Number(outMbps.toFixed(2)),
  }
}

function loadResourceMetrics(): ResourceMetrics {
  const total = os.totalmem()
  const free = os.freemem()
  const network = sampleNetworkMbps()

  return {
    cpuPercent: sampleCpuPercent(),
    memoryPercent: total > 0 ? Number((((total - free) / total) * 100).toFixed(1)) : 0,
    diskPercent: sampleDiskPercent(),
    networkInMbps: network.inMbps,
    networkOutMbps: network.outMbps,
    timestamp: new Date().toISOString(),
  }
}

export async function createApi() {
  const fastify = Fastify({ logger: false })

  await fastify.register(websocket)

  const allowedOrigins = new Set([
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    ...(process.env.UNIFIED_API_ALLOWED_ORIGINS ?? '').split(',').map((origin) => origin.trim()).filter(Boolean),
  ])

  fastify.addHook('onRequest', async (request, reply) => {
    if (request.method !== 'GET' && request.method !== 'OPTIONS') {
      return reply.code(405).header('Allow', 'GET, OPTIONS').send({ error: 'Read-only API' })
    }
    const origin = request.headers.origin
    if (origin && !allowedOrigins.has(origin)) {
      return reply.code(403).send({ error: 'Origin is not allowed' })
    }
    if (origin) {
      reply.header('Access-Control-Allow-Origin', origin)
      reply.header('Vary', 'Origin')
    }
    reply.header('Access-Control-Allow-Methods', 'GET, OPTIONS')
    reply.header('Access-Control-Allow-Headers', 'Content-Type')
    if (request.method === 'OPTIONS') {
      return reply.code(204).send()
    }
  })

  fastify.get('/api/health', async () => ({
    ok: true,
    service: 'unified-api',
    timestamp: new Date().toISOString(),
  }))

  fastify.get('/api/sessions', async (_request, reply) => {
    try {
      return loadSessions()
    } catch {
      return reply.code(503).send({ error: 'Session data is unavailable' })
    }
  })

  fastify.get('/api/sessions/:provider/:id', async (request, reply) => {
    const { provider, id } = request.params as { provider: string; id: string }
    try {
      const session = loadSessions().find((candidate) => candidate.provider === provider && candidate.id === id)
      if (!session) return reply.code(404).send({ error: 'Session not found' })
      return session
    } catch {
      return reply.code(503).send({ error: 'Session data is unavailable' })
    }
  })

  fastify.get('/api/sessions/:provider/:id/messages', async (request, reply) => {
    const { provider, id } = request.params as { provider: string; id: string }
    try {
      const session = loadSessions().find((candidate) => candidate.provider === provider && candidate.id === id)
      if (!session) return reply.code(404).send({ error: 'Session not found' })
      return reply.code(501).send({ error: 'Transcripts are not available from the configured session adapter' })
    } catch {
      return reply.code(503).send({ error: 'Session data is unavailable' })
    }
  })

  fastify.get('/api/fleet', async (_request, reply) => {
    try {
      return loadFleet(loadSessions())
    } catch {
      return reply.code(503).send({ error: 'Fleet data is unavailable' })
    }
  })

  fastify.get('/api/fleet/positions', async (_request, reply) => {
    try {
      return loadFleet(loadSessions()).agents
    } catch {
      return reply.code(503).send({ error: 'Fleet data is unavailable' })
    }
  })

  fastify.get('/api/fleet/terminals', async (_request, reply) => {
    try {
      return loadFleet(loadSessions()).terminals
    } catch {
      return reply.code(503).send({ error: 'Fleet data is unavailable' })
    }
  })

  fastify.get('/api/fleet/alerts', async (_request, reply) => {
    try {
      return loadRiskAlerts()
    } catch {
      return reply.code(503).send({ error: 'Risk alerts are unavailable' })
    }
  })

  fastify.get('/api/portfolio', async (_request, reply) => {
    const portfolio = loadPortfolio()
    if (!portfolio.available) {
      return reply.code(503).send({ error: 'Portfolio snapshot is unavailable' })
    }
    return portfolio
  })

  fastify.get('/api/performance', async (_request, reply) => {
    const performance = loadPerformance()
    if (!performance.available) {
      return reply.code(503).send({ error: 'Performance history is unavailable' })
    }
    return performance
  })

  fastify.get('/api/risk', async (_request, reply) => {
    const portfolio = loadPortfolio()
    if (!portfolio.available) {
      return reply.code(503).send({ error: 'Risk snapshot is unavailable' })
    }
    try {
      return {
        readOnly: true,
        paperOnly: portfolio.broker === 'paper',
        portfolio,
        alerts: loadRiskAlerts(),
        performance: loadPerformance(),
        checkedAt: new Date().toISOString(),
      }
    } catch {
      return reply.code(503).send({ error: 'Risk snapshot is unavailable' })
    }
  })

  fastify.get('/api/settings', async () => ({
    readOnly: true,
    paperOnly: true,
    killSwitch: 'locked',
    allowedOperations: ['read'],
    api: { host: resolveApiHost(), port: 4749 },
    sources: {
      sessions: HIVE_SESSIONS_PATH,
      fleet: HIVE_FLEET_PATH,
      terminals: HIVE_TERMINALS_PATH,
      portfolioDatabase: STATE_DATABASE_PATH,
      portfolioFallback: PORTFOLIO_PATH,
      fundamentals: REPORTS_DIR,
      alerts: LIVE_METRICS_PATH,
    },
  }))

  fastify.get('/api/fundamentals', async () => getFundamentals().rows)

  fastify.get('/api/fundamentals/:symbol', async (request, reply) => {
    const raw = (request.params as { symbol: string }).symbol
    const symbol = decodeURIComponent(raw).toUpperCase()
    const fundamental = getFundamentals().bySymbol.get(symbol)
    if (!fundamental) return reply.code(404).send({ error: 'Fundamental not found' })
    return fundamental
  })

  fastify.get('/api/health/services', async () => loadServiceHealth())

  fastify.get('/api/health/launchd', async () => {
    try {
      return loadLaunchdJobs()
    } catch {
      return []
    }
  })

  fastify.get('/api/health/resources', async () => loadResourceMetrics())

  fastify.get('/api/ws', { websocket: true }, (connection) => {
    try {
      const sessions = loadSessions()
      connection.socket.send(
        JSON.stringify({
          type: 'init',
          timestamp: new Date().toISOString(),
          sessions,
          fleet: loadFleet(sessions),
          fundamentals: getFundamentals().rows.slice(0, 50),
        })
      )
    } catch {
      connection.socket.send(JSON.stringify({ type: 'error', error: 'Session data is unavailable' }))
    }
    connection.socket.on('message', (raw: Buffer) => {
      try {
        const message = JSON.parse(raw.toString())
        if (message.type === 'ping') {
          connection.socket.send(JSON.stringify({ type: 'pong', timestamp: new Date().toISOString() }))
        }
      } catch {
        // Ignore malformed client frames.
      }
    })
  })

  await fastify.ready()
  return fastify
}

function resolveApiHost(configured = process.env.UNIFIED_API_HOST ?? '127.0.0.1'): string {
  const host = configured.trim()
  if (host === '127.0.0.1' || host === '::1' || host === 'localhost') return host
  throw new Error('Unified API is restricted to loopback hosts')
}

export async function startApi() {
  const host = resolveApiHost()
  const fastify = await createApi()
  const started = await fastify.listen({ port: 4749, host })
  fastify.log.level = 'info'
  fastify.log.info(`Unified API server listening on ${started}`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startApi().catch((err) => {
    console.error('API server failed to start:', err)
    process.exit(1)
  })
}

export {
  buildFundamentals,
  getFundamentals,
  parseNetworkBytes,
  resolveApiHost,
  loadSessions,
  loadFleet,
  loadPortfolio,
  loadPerformance,
  loadRiskAlerts,
  loadServiceHealth,
  loadLaunchdJobs,
  loadResourceMetrics,
}

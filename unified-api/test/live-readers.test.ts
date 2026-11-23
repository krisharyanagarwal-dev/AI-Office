import assert from 'node:assert/strict'
import { afterEach, beforeEach, describe, it } from 'node:test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { spawnSync } from 'node:child_process'
import { DatabaseSync } from 'node:sqlite'

const projectRoot = path.resolve(import.meta.dirname, '..')

describe('API module startup', () => {
  it('can be imported without binding the production port', () => {
    const result = spawnSync(process.execPath, [
      '--import', 'tsx',
      '--input-type=module',
      '-e', `import(${JSON.stringify(pathToFileURL(path.join(projectRoot, 'src/index.ts')).href)})`,
    ], {
      cwd: projectRoot,
      encoding: 'utf8',
      timeout: 5000,
    })

    assert.equal(result.status, 0, result.stderr)
  })
})

describe('fleet artifact loading', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-fleet-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('preserves real agent identities and terminal observations', async () => {
    const fleetPath = path.join(fixtureDir, 'fleet.json')
    const terminalsPath = path.join(fixtureDir, 'terminals.json')
    writeFileSync(fleetPath, JSON.stringify({
      updated_at: 1795385151000,
      agents: [{
        id: 'F1',
        name: 'Strategy Monitor',
        role: 'manager',
        floor: 'f1',
        provider: 'opencode',
        status: 'busy',
        processVerified: true,
        activity: 'monitoring',
        processId: 26404,
        lastActiveSecAgo: 12,
      }],
    }))
    writeFileSync(terminalsPath, JSON.stringify({
      collected_at: '2026-11-23T17:48:17+00:00',
      agent_sessions: [{
        session_id: 'sess-opencode-39343',
        agent_id: 'opencode-39343',
        process_id: 39343,
        provider: 'opencode',
        cwd: '/Users/aryanagarwal',
        status: 'ACTIVE',
        process_alive: true,
      }],
      processes: [],
      shell_terminals: [{ pid: 38552, tty: 'ttys000', name: '-zsh', command: '-zsh', cwd: '/Users/aryanagarwal' }],
    }))

    const { loadFleet } = await import('../src/index.ts')
    const fleet = loadFleet([], { fleetPath, terminalsPath })

    assert.deepEqual(fleet.agents, [{
      id: 'F1',
      name: 'Strategy Monitor',
      role: 'manager',
      floor: 'f1',
      provider: 'opencode',
      status: 'busy',
      processVerified: true,
      activity: 'monitoring',
      processId: 26404,
      lastActiveSecAgo: 12,
    }])
    assert.equal(fleet.terminals.length, 2)
    assert.deepEqual(fleet.terminals.map((terminal) => terminal.id), ['session:sess-opencode-39343', 'shell:38552'])
    assert.equal(fleet.terminals[0].kind, 'agent_session')
    assert.equal(fleet.terminals[0].processAlive, true)
    assert.equal(fleet.terminals[1].kind, 'shell')
    assert.equal(fleet.observedAt, '2026-11-23T17:48:17.000Z')
  })

  it('reports unavailable instead of inventing agents when artifacts are missing', async () => {
    const { loadFleet } = await import('../src/index.ts')
    assert.throws(() => loadFleet([], {
      fleetPath: path.join(fixtureDir, 'missing-fleet.json'),
      terminalsPath: path.join(fixtureDir, 'missing-terminals.json'),
    }), /Fleet artifacts are unavailable/)
  })
})

describe('session freshness', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-sessions-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('exposes process liveness and heartbeat age instead of implying all sessions are healthy', async () => {
    const sessionsPath = path.join(fixtureDir, 'sessions.json')
    writeFileSync(sessionsPath, JSON.stringify({
      sessions: [{
        session_id: 'sess-stale',
        agent_id: 'F1',
        process_id: 123,
        provider: 'opencode',
        status: 'HEALTHY',
        started_at: '2026-11-20T00:00:00Z',
        last_heartbeat: '2026-11-20T01:00:00Z',
        updated_at: '2026-11-20T01:00:00Z',
        process_alive: false,
      }],
    }))

    const { loadSessions } = await import('../src/index.ts')
    const sessions = loadSessions({
      sessionsPath,
      now: new Date('2026-11-23T17:00:00Z').getTime(),
    })

    assert.equal(sessions[0].processAlive, false)
    assert.equal(sessions[0].stale, true)
    assert.equal(sessions[0].heartbeatAgeSeconds, 316800)
    assert.equal(sessions[0].agentId, 'F1')
  })
})

describe('SQLite portfolio and performance loading', () => {
  let fixtureDir: string
  let databasePath: string
  const snapshotTime = 1795385151.7953339
  const now = new Date((snapshotTime + 24 * 60) * 1000)

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-sqlite-'))
    databasePath = path.join(fixtureDir, 'state.db')
    const db = new DatabaseSync(databasePath)
    db.exec('CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL, timestamp REAL NOT NULL, category TEXT DEFAULT \'general\')')
    const insert = db.prepare('INSERT INTO state (key, value, timestamp, category) VALUES (?, ?, ?, ?)')
    insert.run('execution_state', JSON.stringify({
      broker: 'paper',
      positions: { NIFTY: { quantity: 2, avg_entry_price: 100, unrealized_pnl: 4, realized_pnl: 1 } },
      balances: { USDT: 800 },
      saved_at: snapshotTime,
      peak_equity: 1000,
      max_drawdown: 25,
    }), snapshotTime, 'execution')
    insert.run('last_run', JSON.stringify({
      run_id: 'aio-current',
      started_at: '2026-11-23T03:35:51Z',
      finished_at: '2026-11-23T03:35:52Z',
      paper_only: true,
      dry_run: false,
      symbols: { NIFTY: { executed: [{ status: 'filled' }], rejected: [], errors: [] } },
      portfolio: {
        broker: 'paper', cash: 800, market_value: 200, equity: 1000,
        realized_pnl: 1, unrealized_pnl: 4, total_pnl: 5, peak_equity: 1000,
        max_drawdown: 25, timestamp: snapshotTime,
        positions: { NIFTY: { quantity: 2, avg_entry_price: 100, mark_price: 102, unrealized_pnl: 4, realized_pnl: 1 } },
      },
      errors: [],
    }), snapshotTime, 'all_in_one')
    insert.run('run:aio-current', JSON.stringify({
      run_id: 'aio-current', started_at: '2026-11-23T03:35:51Z', finished_at: '2026-11-23T03:35:52Z',
      paper_only: true, dry_run: false, symbols: { NIFTY: { executed: [{ status: 'filled' }], rejected: [], errors: [] } }, portfolio: { equity: 1000, total_pnl: 5 }, errors: [],
    }), snapshotTime, 'all_in_one_runs')
    insert.run('run:aio-older', JSON.stringify({
      run_id: 'aio-older', started_at: '2026-11-22T03:00:00Z', finished_at: '2026-11-22T03:00:01Z',
      paper_only: true, dry_run: false, symbols: {}, portfolio: { equity: 990, total_pnl: -5 }, errors: ['screener timeout'],
    }), snapshotTime - 86400, 'all_in_one_runs')
    db.close()
    writeFileSync(path.join(fixtureDir, 'fallback.json'), JSON.stringify({
      broker: 'paper', cash: 1, equity: 2, timestamp: snapshotTime, positions: {},
    }))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('uses the SQLite run snapshot ahead of the JSON fallback', async () => {
    const { loadPortfolio } = await import('../src/index.ts')
    const portfolio = loadPortfolio({
      databasePath,
      fallbackPath: path.join(fixtureDir, 'fallback.json'),
      now: now.getTime(),
    })

    assert.equal(portfolio.available, true)
    assert.equal(portfolio.equity, 1000)
    assert.equal(portfolio.cash, 800)
    assert.equal(portfolio.currency, 'USDT')
    assert.equal(portfolio.totalPnl, 5)
    assert.equal(portfolio.positions[0].symbol, 'NIFTY')
    assert.equal(portfolio.positions[0].markPrice, 102)
    assert.equal(portfolio.source, `sqlite:${databasePath}`)
    assert.equal(portfolio.stale, false)
    assert.equal(portfolio.ageMinutes, 24)
  })

  it('returns an honest unavailable snapshot when SQLite and fallback are missing', async () => {
    const { loadPortfolio } = await import('../src/index.ts')
    const portfolio = loadPortfolio({
      databasePath: path.join(fixtureDir, 'missing.db'),
      fallbackPath: path.join(fixtureDir, 'missing.json'),
      now: now.getTime(),
    })

    assert.equal(portfolio.available, false)
    assert.equal(portfolio.equity, null)
    assert.deepEqual(portfolio.positions, [])
    assert.equal(portfolio.stale, true)
  })

  it('derives performance history from unique SQLite runs newest first', async () => {
    const { loadPerformance } = await import('../src/index.ts')
    const performance = loadPerformance({ databasePath })

    assert.equal(performance.available, true)
    assert.equal(performance.source, `sqlite:${databasePath}`)
    assert.deepEqual(performance.runs.map((run) => run.runId), ['aio-current', 'aio-older'])
    assert.equal(performance.runs[0].status, 'success')
    assert.equal(performance.runs[0].filledOrders, 1)
    assert.equal(performance.runs[1].status, 'error')
    assert.equal(performance.latestEquity, 1000)
    assert.equal(performance.bestEquity, 1000)
    assert.equal(performance.worstEquity, 990)
  })
})

describe('fundamentals alert transitions', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-alerts-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('compares current flags against the real top-level symbol state', async () => {
    const metricsPath = path.join(fixtureDir, 'metrics.json')
    const alertStatePath = path.join(fixtureDir, 'alert-state.json')
    writeFileSync(metricsPath, JSON.stringify({
      fundamentals_by_symbol: {
        AAPL: { symbol: 'AAPL', analyzed_at: '2026-11-23T03:00:00Z', valuation_flag: 'Expensive', leverage_flag: 'High', liquidity_flag: null },
      },
    }))
    writeFileSync(alertStatePath, JSON.stringify({
      AAPL: { valuation_flag: 'Fair', leverage_flag: 'Low', liquidity_flag: 'Normal' },
      last_run: '2026-11-23T03:00:00Z',
    }))

    const { loadRiskAlerts } = await import('../src/index.ts')
    const alerts = loadRiskAlerts({ metricsPath, alertStatePath })

    assert.equal(alerts.some((alert) => alert.rule === 'EXPENSIVE_HIGH_LEVERAGE'), true)
    assert.equal(alerts.some((alert) => alert.rule === 'REGIME_CHANGE_TO_EXPENSIVE'), true)
    assert.equal(alerts.some((alert) => alert.rule === 'UNEXPECTED_NA' && alert.details.field === 'liquidity_flag'), true)
  })
})

describe('fundamentals data integrity', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-fundamentals-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  function writeSummary(file: string, rows: string[]) {
    writeFileSync(path.join(fixtureDir, file), [
      'symbol,name,pe_ttm,current_ratio,debt_to_equity,debt_to_equity_unit,analyzed_at',
      ...rows,
    ].join('\n'))
  }

  function emptyMetrics() {
    const liveMetricsPath = path.join(fixtureDir, 'metrics.json')
    writeFileSync(liveMetricsPath, JSON.stringify({ fundamentals_by_symbol: {} }))
    return liveMetricsPath
  }

  it('selects the newest valid analysis instead of the largest CSV', async () => {
    writeSummary('all_stocks_summary_20261120_120000.csv', [
      'OLD1,Old One,10,2,0.2,ratio,2026-11-20T12:00:00Z',
      'OLD2,Old Two,11,2,0.2,ratio,2026-11-20T12:00:00Z',
      'OLD3,Old Three,12,2,0.2,ratio,2026-11-20T12:00:00Z',
    ])
    writeSummary('all_stocks_summary_20261121_120000.csv', [
      'NEW,New One,14,2,0.2,ratio,2026-11-21T12:00:00Z',
    ])
    writeFileSync(path.join(fixtureDir, 'all_stocks_summary_20261122_120000.csv'), 'symbol,name,pe_ttm\nINVALID,Invalid,9\n')

    const { buildFundamentals } = await import('../src/index.ts')
    const dataset = buildFundamentals({ reportsDir: fixtureDir, liveMetricsPath: emptyMetrics() })

    assert.deepEqual(dataset.rows.map((row) => row.symbol), ['NEW'])
    assert.equal(dataset.rows[0].updatedAt, '2026-11-21T12:00:00.000Z')
  })

  it('leaves unknown source timestamps null instead of inventing freshness', async () => {
    writeSummary('all_stocks_summary_20261121_120000.csv', [
      'KNOWN,Known,14,2,0.2,ratio,2026-11-21T12:00:00Z',
    ])
    const liveMetricsPath = path.join(fixtureDir, 'metrics.json')
    writeFileSync(liveMetricsPath, JSON.stringify({
      fundamentals_by_symbol: { UNKNOWN: { symbol: 'UNKNOWN', name: 'Unknown', price: 5 } },
    }))

    const { buildFundamentals } = await import('../src/index.ts')
    const dataset = buildFundamentals({ reportsDir: fixtureDir, liveMetricsPath })

    assert.equal(dataset.bySymbol.get('UNKNOWN')?.updatedAt, null)
  })

  it('scores leverage in ratio units and handles explicit or legacy percent values', async () => {
    writeSummary('all_stocks_summary_20261121_120000.csv', [
      'LOW,Low,,2.5,0.5,ratio,2026-11-21T12:00:00Z',
      'HIGH,High,,2.5,1.5,ratio,2026-11-21T12:00:00Z',
      'PERCENT,Percent,,2.5,150,percent,2026-11-21T12:00:00Z',
      'LEGACY,Legacy,,2.5,150,,2026-11-21T12:00:00Z',
    ])

    const { buildFundamentals } = await import('../src/index.ts')
    const dataset = buildFundamentals({ reportsDir: fixtureDir, liveMetricsPath: emptyMetrics() })

    assert.equal(dataset.bySymbol.get('LOW')?.score, 100)
    assert.equal(dataset.bySymbol.get('HIGH')?.score, 50)
    assert.equal(dataset.bySymbol.get('PERCENT')?.debtToEquity, 1.5)
    assert.equal(dataset.bySymbol.get('PERCENT')?.score, 50)
    assert.equal(dataset.bySymbol.get('LEGACY')?.debtToEquity, 1.5)
    assert.equal(dataset.bySymbol.get('LEGACY')?.score, 50)
  })

  it('reports component-weighted coverage when only one metric in a group exists', async () => {
    writeSummary('all_stocks_summary_20261121_120000.csv', [
      'PARTIAL,Partial,,2.5,,,2026-11-21T12:00:00Z',
    ])

    const { buildFundamentals } = await import('../src/index.ts')
    const dataset = buildFundamentals({ reportsDir: fixtureDir, liveMetricsPath: emptyMetrics() })

    assert.equal(dataset.rows[0].score, 100)
    assert.equal(dataset.rows[0].scoreCoverage, 11.5)
  })
})

describe('alert identity and coverage', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-alert-identity-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('keeps alert episode IDs stable across repolls and reordering', async () => {
    const metricsPath = path.join(fixtureDir, 'metrics.json')
    const alertStatePath = path.join(fixtureDir, 'state.json')
    const aapl = { symbol: 'AAPL', valuation_flag: 'Expensive', leverage_flag: 'High', analyzed_at: '2026-11-23T03:00:00Z' }
    const amzn = { symbol: 'AMZN', liquidity_flag: 'Tight', analyzed_at: '2026-11-23T03:00:00Z' }
    writeFileSync(alertStatePath, '{}')
    writeFileSync(metricsPath, JSON.stringify({ fundamentals_by_symbol: { AAPL: aapl, AMZN: amzn } }))

    const { loadRiskAlerts } = await import('../src/index.ts')
    const first = loadRiskAlerts({ metricsPath, alertStatePath })
    writeFileSync(metricsPath, JSON.stringify({ fundamentals_by_symbol: { AMZN: amzn, AAPL: aapl } }))
    const second = loadRiskAlerts({ metricsPath, alertStatePath })
    const ids = (alerts: Array<{ id: string; rule: string; symbol: string }>) => Object.fromEntries(
      alerts.map((alert) => [`${alert.rule}:${alert.symbol}`, alert.id]),
    )

    assert.deepEqual(ids(first), ids(second))
    assert.ok(first.every((alert) => /^[a-f0-9]{16}$/.test(alert.id)))
  })

  it('rejects missing, empty, array, and symbol-less coverage as unavailable', async () => {
    const metricsPath = path.join(fixtureDir, 'metrics.json')
    const alertStatePath = path.join(fixtureDir, 'state.json')
    writeFileSync(alertStatePath, '{}')
    const { loadRiskAlerts } = await import('../src/index.ts')

    for (const payload of [
      {},
      { fundamentals_by_symbol: {} },
      { fundamentals_by_symbol: [] },
      { fundamentals_by_symbol: { AAPL: { valuation_flag: 'Fair' } } },
    ]) {
      writeFileSync(metricsPath, JSON.stringify(payload))
      assert.throws(() => loadRiskAlerts({ metricsPath, alertStatePath }), /coverage|unavailable/i)
    }
  })
})

describe('portfolio validation', () => {
  let fixtureDir: string

  beforeEach(() => {
    fixtureDir = mkdtempSync(path.join(tmpdir(), 'unified-api-portfolio-validation-'))
  })

  afterEach(() => {
    rmSync(fixtureDir, { recursive: true, force: true })
  })

  it('preserves an explicit currency and rejects malformed positions instead of inventing zeros', async () => {
    const fallbackPath = path.join(fixtureDir, 'portfolio.json')
    const valid = {
      broker: 'paper', currency: 'INR', cash: 800, market_value: 200, equity: 1000,
      realized_pnl: 1, unrealized_pnl: 4, total_pnl: 5, timestamp: 1795385151,
      positions: { NIFTY: { quantity: 2, avg_entry_price: 100, mark_price: 102, unrealized_pnl: 4, realized_pnl: 1 } },
    }
    writeFileSync(fallbackPath, JSON.stringify(valid))
    const { loadPortfolio } = await import('../src/index.ts')
    const paths = { databasePath: path.join(fixtureDir, 'missing.db'), fallbackPath }
    assert.equal(loadPortfolio(paths).currency, 'INR')

    writeFileSync(fallbackPath, JSON.stringify({
      ...valid,
      positions: { NIFTY: { ...valid.positions.NIFTY, quantity: 'not-a-number' } },
    }))
    const malformed = loadPortfolio(paths)
    assert.equal(malformed.available, false)
    assert.deepEqual(malformed.positions, [])
    assert.equal(malformed.equity, null)
  })
})

describe('system health probe honesty', () => {
  it('throws when launchctl fails instead of reporting no jobs', async () => {
    const { loadLaunchdJobs } = await import('../src/index.ts')
    assert.throws(() => loadLaunchdJobs({ launchctlPath: '/usr/bin/false' }), /launchctl|launchd/i)
  })

  it('parses one real en0 counter row by header position', async () => {
    const { parseNetworkBytes } = await import('../src/index.ts')
    const output = [
      'Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll',
      'en0 1500 <Link#11> 8a:67:a1:84:5e:ce 100 0 1000 50 0 500 0',
      'en0 1500 192.168.29 192.168.29.218 100 - 1000 50 - 500 -',
    ].join('\n')

    assert.deepEqual(parseNetworkBytes(output), { received: 1000, sent: 500 })
    assert.equal(parseNetworkBytes('Name Mtu Network\nen0 1500 <Link#11>'), null)
    assert.equal(parseNetworkBytes('Name Ibytes Obytes\nen0 nope 500'), null)
  })

  it('allows only loopback API binds', async () => {
    const { resolveApiHost } = await import('../src/index.ts')
    assert.equal(resolveApiHost('127.0.0.1'), '127.0.0.1')
    assert.equal(resolveApiHost('::1'), '::1')
    assert.throws(() => resolveApiHost('0.0.0.0'), /loopback/i)
  })
})

describe('read-only API routes', () => {
  it('serves performance risk and settings through Fastify injection', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const performance = await app.inject({ method: 'GET', url: '/api/performance' })
      assert.equal(performance.statusCode, 200)
      assert.equal(performance.json().source, 'sqlite:/Users/aryanagarwal/AI-Office/data/all_in_one_state.db')

      const risk = await app.inject({ method: 'GET', url: '/api/risk' })
      assert.equal(risk.statusCode, 200)
      assert.equal(risk.json().readOnly, true)
      assert.equal(risk.json().portfolio.broker, 'paper')
      assert.equal(Array.isArray(risk.json().alerts), true)

      const settings = await app.inject({ method: 'GET', url: '/api/settings' })
      assert.equal(settings.statusCode, 200)
      assert.equal(settings.json().readOnly, true)
      assert.equal(settings.json().paperOnly, true)
      assert.equal(settings.json().killSwitch, 'locked')
      assert.deepEqual(settings.json().allowedOperations, ['read'])

      const mutation = await app.inject({ method: 'POST', url: '/api/portfolio' })
      assert.equal(mutation.statusCode, 405)
      assert.deepEqual(mutation.json(), { error: 'Read-only API' })
    } finally {
      await app.close()
    }
  })
})

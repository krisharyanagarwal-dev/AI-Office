import assert from 'node:assert/strict'
import { afterEach, describe, it } from 'node:test'
import { DatabaseSync } from 'node:sqlite'

const STATE_DATABASE_PATH = '/Users/aryanagarwal/AI-Office/data/all_in_one_state.db'

function eraseControlState(): void {
  const db = new DatabaseSync(STATE_DATABASE_PATH)
  try {
    db.exec("DELETE FROM state WHERE key IN ('bot_control', 'risk_limits') AND category = 'all_in_one'")
  } finally {
    db.close()
  }
}

afterEach(() => eraseControlState())

function postJson(app: unknown, url: string, body: unknown) {
  return app.inject({
    method: 'POST',
    url,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

describe('control endpoints', () => {
  it('GET /api/bot/state returns defaults when nothing is persisted', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const res = await app.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(res.statusCode, 200)
      const body = res.json() as {
        bot: { action: string | null; killSwitch: boolean; requestedAt: string | null; updatedAt: string | null }
        risk: { max_symbol_notional: number; max_symbols: number; kill_switch: boolean }
        paperOnly: boolean
      }
      assert.deepEqual(body.bot, {
        action: null,
        killSwitch: false,
        requestedAt: null,
        updatedAt: null,
      })
      assert.equal(body.risk.max_symbol_notional, 10_000)
      assert.equal(body.risk.max_symbols, 3)
      assert.equal(body.risk.kill_switch, false)
      assert.equal(body.paperOnly, true)
    } finally {
      await app.close()
    }
  })

  it('POST /api/bot/control persists start and stop actions', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const start = await postJson(app, '/api/bot/control', { action: 'start' })
      assert.equal(start.statusCode, 200)
      assert.equal(start.json().ok, true)
      assert.equal(start.json().action, 'start')
      assert.equal(typeof start.json().updatedAt, 'string')

      const state = await app.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(state.json().bot.action, 'start')

      const stop = await postJson(app, '/api/bot/control', { action: 'stop' })
      assert.equal(stop.statusCode, 200)
      assert.equal(stop.json().action, 'stop')
      assert.equal(state.json().bot.action, 'start')

      const stateAfter = await app.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(stateAfter.json().bot.action, 'stop')
    } finally {
      await app.close()
    }
  })

  it('rejects invalid control actions', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const bad = await postJson(app, '/api/bot/control', { action: 'reset' })
      assert.equal(bad.statusCode, 400)
      assert.equal(bad.json().error, 'Invalid control action: expected { action: "start" | "stop" }')

      const missing = await postJson(app, '/api/bot/control', {})
      assert.equal(missing.statusCode, 400)
    } finally {
      await app.close()
    }
  })

  it('POST /api/bot/kill-switch toggles and preserves the pending action', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      await postJson(app, '/api/bot/control', { action: 'start' })

      const armed = await postJson(app, '/api/bot/kill-switch', { enabled: true })
      assert.equal(armed.statusCode, 200)
      assert.equal(armed.json().ok, true)
      assert.equal(armed.json().killSwitch, true)

      const state = await app.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(state.json().bot.killSwitch, true)
      assert.equal(state.json().bot.action, 'start')

      const disarmed = await postJson(app, '/api/bot/kill-switch', { enabled: false })
      assert.equal(disarmed.json().killSwitch, false)
      assert.equal(state.json().bot.action, 'start')

      const bad = await postJson(app, '/api/bot/kill-switch', { enabled: 'yes' })
      assert.equal(bad.statusCode, 400)
    } finally {
      await app.close()
    }
  })

  it('POST /api/risk/limits merges a partial patch with persisted defaults', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const patched = await postJson(app, '/api/risk/limits', {
        max_symbol_notional: 1_234,
        max_daily_loss_pct: 0.05,
      })
      assert.equal(patched.statusCode, 200)
      assert.equal(patched.json().riskLimits.max_symbol_notional, 1_234)
      assert.equal(patched.json().riskLimits.max_daily_loss_pct, 0.05)
      assert.equal(patched.json().riskLimits.max_gross_notional, 20_000)
      assert.equal(patched.json().riskLimits.max_symbols, 3)

      const state = await app.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(state.json().risk.max_symbol_notional, 1_234)
      assert.equal(state.json().risk.max_gross_notional, 20_000)

      const bad = await postJson(app, '/api/risk/limits', { max_symbols: 1.5 })
      assert.equal(bad.statusCode, 400)
    } finally {
      await app.close()
    }
  })

  it('control state persists across app instances', async () => {
    const { createApi } = await import('../src/index.ts')
    const first = await createApi()
    await postJson(first, '/api/bot/control', { action: 'stop' })
    await postJson(first, '/api/bot/kill-switch', { enabled: true })
    await first.close()

    const second = await createApi()
    try {
      const state = await second.inject({ method: 'GET', url: '/api/bot/state' })
      assert.equal(state.json().bot.action, 'stop')
      assert.equal(state.json().bot.killSwitch, true)
    } finally {
      await second.close()
    }
  })

  it('non-control routes remain read-only', async () => {
    const { createApi } = await import('../src/index.ts')
    const app = await createApi()
    try {
      const portfolio = await app.inject({ method: 'POST', url: '/api/portfolio' })
      assert.equal(portfolio.statusCode, 405)
      assert.deepEqual(portfolio.json(), { error: 'Read-only API' })

      const risk = await app.inject({ method: 'POST', url: '/api/risk' })
      assert.equal(risk.statusCode, 405)
    } finally {
      await app.close()
    }
  })
})

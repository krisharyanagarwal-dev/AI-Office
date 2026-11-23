import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import assert from 'node:assert/strict'
import vm from 'node:vm'

const dashboardRoot = path.resolve(import.meta.dirname, '..')
const baseUrl = process.env.DASHBOARD_URL ?? 'http://localhost:5173'
const blockedApiUrl = (route) => `*://${new URL(baseUrl).host}${route}`
const chromePath = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const themeOnly = process.argv.includes('--theme-only')

function verifyThemeBootstrap() {
  const html = readFileSync(path.join(dashboardRoot, 'index.html'), 'utf8')
  const scripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)]
  const bootstrap = scripts.find(([, attributes]) => !attributes.includes('type="module"'))
  assert.ok(bootstrap, 'index.html must initialize the stored theme before React starts')

  const moduleIndex = html.indexOf('type="module"')
  assert.ok(bootstrap.index < moduleIndex, 'theme bootstrap must precede the React module')

  for (const [stored, expectedDark, expectedColor] of [
    [null, true, '#070b14'],
    ['light', false, '#f4f7fb'],
    ['dark', true, '#070b14'],
  ]) {
    let dark = true
    let themeColor = ''
    const context = {
      localStorage: { getItem: (key) => key === 'alpha-theme' ? stored : null },
      document: {
        documentElement: {
          classList: {
            toggle: (_name, force) => { dark = force },
          },
        },
        querySelector: (selector) => selector === 'meta[name="theme-color"]'
          ? { setAttribute: (_name, value) => { themeColor = value } }
          : null,
      },
    }

    vm.runInNewContext(bootstrap[2], context)
    assert.equal(dark, expectedDark, `stored theme ${stored ?? 'unset'} must select the correct color scheme`)
    assert.equal(themeColor, expectedColor, `stored theme ${stored ?? 'unset'} must update theme-color`)
  }

  return { passed: true, cases: ['unset', 'light', 'dark'] }
}

if (themeOnly) {
  console.log(JSON.stringify({ themeBootstrap: verifyThemeBootstrap() }, null, 2))
  process.exit(0)
}

async function fetchJson(route) {
  const response = await fetch(`${baseUrl}${route}`)
  assert.ok(response.ok, `${route} returned ${response.status}`)
  return response.json()
}

const [sessions, portfolio, alerts, services, fundamentals, performance, risk, settings] = await Promise.all([
  fetchJson('/api/sessions'),
  fetchJson('/api/portfolio'),
  fetchJson('/api/fleet/alerts'),
  fetchJson('/api/health/services'),
  fetchJson('/api/fundamentals'),
  fetchJson('/api/performance'),
  fetchJson('/api/risk'),
  fetchJson('/api/settings'),
])
assert.ok(Array.isArray(sessions), '/api/sessions must return an array')
assert.ok(Array.isArray(alerts), '/api/fleet/alerts must return an array')
assert.ok(Array.isArray(services), '/api/health/services must return an array')
assert.ok(Array.isArray(fundamentals), '/api/fundamentals must return an array')
assert.ok(Array.isArray(performance.runs), '/api/performance must include runs')
assert.equal(risk.readOnly, true, '/api/risk must remain read-only')
assert.equal(settings.killSwitch, 'locked', '/api/settings must expose a locked kill switch')
assert.ok(sessions.every((session) => session.source === 'live'), '/api/sessions must contain only live rows')
assert.ok(!sessions.some((session) => session.id.startsWith('fixture-')), '/api/sessions must not contain fixtures')

if (sessions.length > 0) {
  const session = sessions[0]
  const transcript = await fetch(`${baseUrl}/api/sessions/${encodeURIComponent(session.provider)}/${encodeURIComponent(session.id)}/messages`)
  assert.equal(transcript.status, 501, 'unavailable transcripts must return 501')
}

const currencySymbol = portfolio.currency === 'INR' ? '₹' : '$'
const formatMoney = (value) => `${currencySymbol}${value.toLocaleString('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})}`
const expectedEquity = portfolio.equity === null ? 'Unavailable' : formatMoney(portfolio.equity)
const alertTitles = {
  EXPENSIVE_HIGH_LEVERAGE: 'Expensive valuation with high leverage',
  TIGHT_LIQUIDITY: 'Tight liquidity',
  REGIME_CHANGE_TO_EXPENSIVE: 'Valuation regime changed to expensive',
  UNEXPECTED_NA: 'Metric became unavailable',
}

const port = 9333
const profile = mkdtempSync(path.join(tmpdir(), 'alpha-dashboard-chrome-'))
const chrome = spawn(chromePath, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  '--remote-allow-origins=*',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  '--window-size=1440,1000',
  'about:blank',
], { stdio: 'ignore' })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const results = {
  themeBootstrap: verifyThemeBootstrap(),
  checks: {},
  consoleErrors: [],
  exceptions: [],
  failedRequests: [],
  screenshots: {},
}

function failedBooleanPaths(value, prefix = 'checks') {
  if (typeof value === 'boolean') return value ? [] : [prefix]
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).flatMap(([key, child]) => failedBooleanPaths(child, `${prefix}.${key}`))
}

async function getTarget() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`)
      const pages = await response.json()
      if (pages[0]?.webSocketDebuggerUrl) return pages[0]
    } catch {}
    await delay(100)
  }
  throw new Error('Chrome DevTools endpoint did not start')
}

const target = await getTarget()
const socket = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})

let nextId = 1
const pending = new Map()
const eventHandlers = new Map()
const requestUrls = new Map()

socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (message.id) {
    const handler = pending.get(message.id)
    if (!handler) return
    pending.delete(message.id)
    if (message.error) handler.reject(new Error(JSON.stringify(message.error)))
    else handler.resolve(message.result)
    return
  }
  for (const handler of eventHandlers.get(message.method) ?? []) handler(message.params)
})

function on(method, handler) {
  const handlers = eventHandlers.get(method) ?? []
  handlers.push(handler)
  eventHandlers.set(method, handlers)
}

function send(method, params = {}) {
  const id = nextId += 1
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    socket.send(JSON.stringify({ id, method, params }))
  })
}

async function evaluate(expression) {
  const response = await send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
    userGesture: true,
  })
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text || 'Page evaluation failed')
  }
  return response.result.value
}

async function waitFor(expression, timeout = 15000) {
  const started = Date.now()
  while (Date.now() - started < timeout) {
    if (await evaluate(expression)) return
    await delay(100)
  }
  throw new Error(`Timed out waiting for: ${expression}`)
}

async function click(selector) {
  const clicked = await evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)})) && (document.querySelector(${JSON.stringify(selector)}).click(), true)`)
  if (!clicked) throw new Error(`Element not found: ${selector}`)
}

async function clickButton(label, scope = 'document') {
  const clicked = await evaluate(`(() => {
    const button = [...${scope}.querySelectorAll('button')].find((item) => item.textContent?.trim() === ${JSON.stringify(label)})
    if (!button) return false
    button.click()
    return true
  })()`)
  if (!clicked) throw new Error(`Button not found: ${label}`)
}

async function navigate(route = '/') {
  await send('Page.navigate', { url: `${baseUrl}${route}` })
  await waitFor(`document.readyState === 'complete' && location.pathname === ${JSON.stringify(route)} && Boolean(document.querySelector('main'))`)
  await waitFor(`document.querySelectorAll('.skeleton').length === 0`)
}

async function screenshot(name, fullPage = true) {
  await waitFor(`[...document.querySelectorAll('.animate-rise-in')].every((element) => getComputedStyle(element).opacity === '1')`)
  const params = { format: 'png', captureBeyondViewport: fullPage, fromSurface: true }
  if (fullPage) {
    const metrics = await send('Page.getLayoutMetrics')
    params.clip = {
      x: 0,
      y: 0,
      width: metrics.cssContentSize.width,
      height: metrics.cssContentSize.height,
      scale: 1,
    }
  }
  const { data } = await send('Page.captureScreenshot', params)
  const filePath = `/tmp/${name}.png`
  writeFileSync(filePath, Buffer.from(data, 'base64'))
  results.screenshots[name] = filePath
}

try {
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')
  await send('Log.enable')

  on('Runtime.consoleAPICalled', (event) => {
    if (event.type === 'error') {
      results.consoleErrors.push(event.args.map((arg) => arg.value ?? arg.description ?? '').join(' '))
    }
  })
  on('Runtime.exceptionThrown', (event) => {
    results.exceptions.push(event.exceptionDetails.text)
  })
  on('Log.entryAdded', (event) => {
    if (event.entry.level === 'error') results.consoleErrors.push(event.entry.text)
  })
  on('Network.requestWillBeSent', (event) => {
    requestUrls.set(event.requestId, event.request.url)
  })
  on('Network.loadingFailed', (event) => {
    results.failedRequests.push({ url: requestUrls.get(event.requestId) ?? '', error: event.errorText })
  })
  on('Network.responseReceived', (event) => {
    if (event.response.status >= 400) {
      results.failedRequests.push({ url: event.response.url, status: event.response.status })
    }
  })

  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  })
  await navigate()

  results.checks.desktopRender = await evaluate(`(() => {
    const text = document.body.innerText
    return {
      correctTitle: document.title === 'Alpha · Trading Command Center',
      darkTheme: document.documentElement.classList.contains('dark') && getComputedStyle(document.body).backgroundColor === 'rgb(7, 10, 19)',
      commandCenter: document.querySelector('h1')?.textContent?.trim() === 'Command Center',
      realEquity: ${JSON.stringify(expectedEquity)} === 'Unavailable' || text.includes(${JSON.stringify(expectedEquity)}),
      positionsMatchApi: ${JSON.stringify(portfolio.positions.length)} === 0 ? text.includes('No open positions') : ${JSON.stringify(portfolio.positions.flatMap((position) => [position.symbol, position.side]))}.every((value) => text.includes(value)),
      alertsMatchApi: ${JSON.stringify(alerts.length)} === 0 ? text.includes('No active alerts') : ${JSON.stringify(alerts.map((alert) => alertTitles[alert.rule] ?? alert.rule))}.every((value) => text.includes(value)),
      staleWarning: ${JSON.stringify(portfolio.stale)} ? text.includes('stale') : true,
      sessionsMatchApi: ${JSON.stringify(sessions.length)} === 0 ? text.includes('No active sessions') : ${JSON.stringify(sessions.slice(0, 5).map((session) => session.title || `${session.provider} · ${session.id}`))}.every((value) => text.includes(value)),
      servicesRendered: ${JSON.stringify(services.map((service) => service.name))}.every((value) => text.includes(value)),
      noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    }
  })()`)
  await screenshot('alpha-dashboard-desktop')

  await click('button[aria-label="Switch to light mode"]')
  await waitFor(`!document.documentElement.classList.contains('dark') && localStorage.getItem('alpha-theme') === 'light'`)
  results.checks.themeLight = await evaluate(`!document.documentElement.classList.contains('dark') && localStorage.getItem('alpha-theme') === 'light' && getComputedStyle(document.body).backgroundColor === 'rgb(248, 250, 252)' && document.querySelector('meta[name="theme-color"]')?.content === '#f4f7fb'`)
  await navigate()
  results.checks.themePersisted = await evaluate(`!document.documentElement.classList.contains('dark') && localStorage.getItem('alpha-theme') === 'light'`)
  await click('button[aria-label="Switch to dark mode"]')
  await waitFor(`document.documentElement.classList.contains('dark') && localStorage.getItem('alpha-theme') === 'dark'`)
  results.checks.themeColorUpdated = await evaluate(`document.querySelector('meta[name="theme-color"]')?.content === '#070b14'`)

  const unreadBefore = await evaluate(`Number(document.querySelector('a[href="/alerts"]')?.getAttribute('aria-label')?.match(/\\d+/)?.[0] ?? 0)`)
  if (unreadBefore > 0) {
    await evaluate(`[...document.querySelectorAll('#alerts button')].find((button) => button.textContent?.trim() === 'Acknowledge')?.click()`)
    await waitFor(`document.querySelector('a[href="/alerts"]')?.getAttribute('aria-label') === 'Alerts (${unreadBefore - 1} unread)'`)
    results.checks.alertAcknowledge = true
  }

  await click('button[aria-label="Collapse sidebar"]')
  await waitFor(`document.querySelector('#dashboard-sidebar')?.getBoundingClientRect().width <= 65`)
  results.checks.sidebarCollapse = true
  await click('button[aria-label="Expand sidebar"]')
  await waitFor(`document.querySelector('#dashboard-sidebar')?.getBoundingClientRect().width >= 250`)

  await click('a[href="/fundamentals"]')
  await waitFor(`location.pathname === '/fundamentals'`)
  await waitFor(`Boolean(document.querySelector('table')) || document.body.innerText.includes('No fundamentals available.')`)
  results.checks.fundamentalsNavigation = await evaluate(`({ path: location.pathname, hasShell: Boolean(document.querySelector('#dashboard-sidebar')) && Boolean(document.querySelector('header')), hasTable: Boolean(document.querySelector('table')) })`)

  if (fundamentals.length > 0) {
    const searchSymbol = fundamentals.find((row) => row.symbol.length >= 3)?.symbol
    const submitted = await evaluate(`(() => {
      const input = document.querySelector('header input[aria-label="Search fundamentals"]')
      if (!input) return false
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      setValue.call(input, ${JSON.stringify(searchSymbol)})
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.form?.requestSubmit()
      return true
    })()`)
    assert.ok(submitted, 'Header must expose a working fundamentals search input')
    await waitFor(`location.pathname === '/fundamentals' && new URLSearchParams(location.search).get('search') === ${JSON.stringify(searchSymbol)}`)
    await waitFor(`document.querySelector('table')?.innerText.includes(${JSON.stringify(searchSymbol)})`)
    results.checks.fundamentalsSearch = await evaluate(`(() => {
      const query = new URLSearchParams(location.search).get('search')?.toLowerCase() ?? ''
      const rows = [...document.querySelectorAll('table tbody tr')].filter((row) => !row.textContent?.includes('No fundamentals'))
      return rows.length > 0 && rows.every((row) => row.textContent?.toLowerCase().includes(query))
    })()`)
  }

  results.checks.routeShells = {}
  for (const route of [
    { path: '/sessions', ready: `document.body.innerText.includes('Live sessions') || document.body.innerText.includes('Sessions unavailable') || document.body.innerText.includes('No active sessions')` },
    { path: '/fundamentals', ready: `Boolean(document.querySelector('table')) || document.body.innerText.includes('No fundamentals available.')` },
    { path: '/health', ready: `Boolean(document.querySelector('article')) || document.body.innerText.includes('System health is unavailable')` },
    { path: '/health/launchd', ready: `Boolean(document.querySelector('table')) || document.body.innerText.includes('Launchd jobs unavailable') || document.body.innerText.includes('No launchd jobs')` },
    { path: '/health/resources', ready: `document.body.innerText.includes('System Resource Metrics') || document.body.innerText.includes('Resource metrics unavailable')` },
  ]) {
    await navigate(route.path)
    await waitFor(route.ready)
    results.checks.routeShells[route.path] = await evaluate(`({ path: location.pathname, hasSidebar: Boolean(document.querySelector('#dashboard-sidebar')), hasHeader: Boolean(document.querySelector('header')), hasMain: Boolean(document.querySelector('main')), content: document.querySelector('main')?.innerText.length ?? 0 })`)
  }

  results.checks.requiredPages = {}
  for (const route of [
    { path: '/positions', heading: 'Positions', token: portfolio.positions[0]?.symbol ?? 'No open positions' },
    { path: '/alerts', heading: 'Risk Alerts', token: alerts[0] ? alertTitles[alerts[0].rule] ?? alerts[0].rule : 'No active alerts' },
    { path: '/performance', heading: 'Performance', token: performance.runs[0]?.runId ?? 'No performance runs available' },
    { path: '/risk', heading: 'Risk Overview', token: 'Kill switch locked' },
    { path: '/settings', heading: 'Settings', token: 'Live data sources' },
  ]) {
    await navigate(route.path)
    results.checks.requiredPages[route.path] = await evaluate(`(() => {
      const text = document.querySelector('main')?.innerText ?? ''
      return {
        correctHeading: document.querySelector('main h1')?.textContent?.trim() === ${JSON.stringify(route.heading)},
        liveContent: text.includes(${JSON.stringify(route.token)}),
        hasShell: Boolean(document.querySelector('#dashboard-sidebar')) && Boolean(document.querySelector('header')),
        noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      }
    })()`)
    await screenshot(`alpha-dashboard-${route.path.slice(1)}`)
  }

  results.checks.primaryNavigation = await evaluate(`(() => ({
    headerAlertsRoute: document.querySelector('header a[href="/alerts"]')?.getAttribute('aria-label')?.startsWith('Alerts') ?? false,
    destinations: ${JSON.stringify(['/', '/sessions', '/fundamentals', '/health', '/positions', '/alerts', '/performance', '/risk', '/settings'])}.every((href) => Boolean(document.querySelector('#dashboard-sidebar a[href="' + href + '"]'))),
  }))()`)

  await send('Network.setBlockedURLs', { urls: [blockedApiUrl('/api/fundamentals')] })
  await navigate('/fundamentals')
  await waitFor(`document.body.innerText.includes('Fundamentals unavailable')`)
  results.checks.fundamentalsFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`Boolean(document.querySelector('table')) || document.body.innerText.includes('No fundamentals available.')`)
  results.checks.fundamentalsFailureRetry = true

  await send('Network.setBlockedURLs', { urls: [blockedApiUrl('/api/fundamentals')] })
  await navigate('/fundamentals/filter')
  await waitFor(`document.body.innerText.includes('Fundamentals unavailable')`)
  results.checks.fundamentalsFilterFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`Boolean(document.querySelector('#sector-filter'))`)
  results.checks.fundamentalsFilterFailureRetry = true

  if (fundamentals.length > 0) {
    const fundamental = fundamentals[0]
    const cardPath = `/fundamentals/${encodeURIComponent(fundamental.symbol)}`
    await navigate(cardPath)
    await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(fundamental.name)})`)
    results.checks.fundamentalsCardRender = true

    await send('Network.setBlockedURLs', { urls: [blockedApiUrl(`/api/fundamentals/${encodeURIComponent(fundamental.symbol)}`)] })
    await navigate(cardPath)
    await waitFor(`document.body.innerText.includes('Fundamentals unavailable')`)
    results.checks.fundamentalsCardFailureState = true
    await send('Network.setBlockedURLs', { urls: [] })
    await clickButton('Retry')
    await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(fundamental.name)})`)
    results.checks.fundamentalsCardFailureRetry = true
  }

  if (sessions.length > 0) {
    const session = sessions[0]
    const detailPath = `/sessions/${encodeURIComponent(session.provider)}/${encodeURIComponent(session.id)}`
    await navigate(detailPath)
    await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(session.title || session.id)})`)
    await waitFor(`document.querySelector('main')?.innerText.includes('Transcript unavailable from the configured session adapter.')`)
    results.checks.transcriptUnavailable = true

    await send('Network.setBlockedURLs', { urls: [blockedApiUrl(`/api/sessions/${encodeURIComponent(session.provider)}/${encodeURIComponent(session.id)}`)] })
    await navigate(detailPath)
    await waitFor(`document.body.innerText.includes('Session unavailable')`)
    results.checks.sessionDetailFailureState = true
    await send('Network.setBlockedURLs', { urls: [] })
    await clickButton('Retry')
    await waitFor(`document.querySelector('main')?.innerText.includes(${JSON.stringify(session.title || session.id)})`)
    results.checks.sessionDetailFailureRetry = true
  }

  await navigate()
  await send('Network.setBlockedURLs', { urls: ['*/api/portfolio'] })
  await navigate()
  await waitFor(`document.body.innerText.includes('Some live feeds could not be loaded.') && document.body.innerText.includes('Portfolio unavailable')`)
  results.checks.portfolioFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`document.body.innerText.includes(${JSON.stringify(expectedEquity)}) && !document.body.innerText.includes('Some live feeds could not be loaded.')`)
  results.checks.portfolioFailureRetry = true

  await send('Network.setBlockedURLs', { urls: ['*/api/fleet/alerts'] })
  await navigate()
  await waitFor(`document.body.innerText.includes('Risk alerts unavailable')`)
  results.checks.alertsFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`!document.body.innerText.includes('Risk alerts unavailable') && !document.body.innerText.includes('Some live feeds could not be loaded.')`)
  results.checks.alertsFailureRetry = true

  await send('Network.setBlockedURLs', { urls: ['*/api/sessions'] })
  await navigate()
  await waitFor(`document.body.innerText.includes('Sessions unavailable')`)
  results.checks.sessionsFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`!document.body.innerText.includes('Sessions unavailable') && !document.body.innerText.includes('Some live feeds could not be loaded.')`)
  results.checks.sessionsFailureRetry = true

  await send('Network.setBlockedURLs', { urls: ['*/api/health/services'] })
  await navigate('/health')
  await waitFor(`document.body.innerText.includes('System health is unavailable')`)
  results.checks.healthFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`document.querySelectorAll('article').length > 0`)
  results.checks.healthFailureRetry = true

  await send('Network.setBlockedURLs', { urls: ['*/api/health/launchd'] })
  await navigate('/health/launchd')
  await waitFor(`document.body.innerText.includes('Launchd jobs unavailable')`)
  results.checks.launchdFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`Boolean(document.querySelector('table'))`)
  results.checks.launchdFailureRetry = true

  await send('Network.setBlockedURLs', { urls: ['*/api/health/resources'] })
  await navigate('/health/resources')
  await waitFor(`document.body.innerText.includes('Resource metrics unavailable')`)
  results.checks.resourcesFailureState = true
  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  await waitFor(`document.body.innerText.includes('System Resource Metrics')`)
  results.checks.resourcesFailureRetry = true

  results.checks.requiredPageRecovery = {}
  for (const route of [
    { path: '/positions', api: '/api/portfolio', failure: 'Portfolio unavailable', recovered: 'Open positions' },
    { path: '/alerts', api: '/api/fleet/alerts', failure: 'Risk alerts unavailable', recovered: 'Risk Alerts' },
    { path: '/performance', api: '/api/performance', failure: 'Performance unavailable', recovered: 'Performance' },
    { path: '/risk', api: '/api/risk', failure: 'Risk overview unavailable', recovered: 'Kill switch locked' },
    { path: '/settings', api: '/api/settings', failure: 'Settings unavailable', recovered: 'Live data sources' },
  ]) {
    await send('Network.setBlockedURLs', { urls: [blockedApiUrl(route.api)] })
    await navigate(route.path)
    await waitFor(`document.body.innerText.includes(${JSON.stringify(route.failure)})`)
    results.checks.requiredPageRecovery[`${route.path}FailureState`] = true
    await send('Network.setBlockedURLs', { urls: [] })
    await clickButton('Retry')
    await waitFor(`document.body.innerText.includes(${JSON.stringify(route.recovered)})`)
    results.checks.requiredPageRecovery[`${route.path}FailureRetry`] = true
  }

  await navigate()
  await send('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  })
  await delay(250)
  await waitFor(`document.querySelector('button[aria-label="Open navigation"]')?.getBoundingClientRect().width > 0`)
  results.checks.mobileLayout = await evaluate(`(() => {
    const sidebar = document.querySelector('#dashboard-sidebar')
    const openButton = document.querySelector('button[aria-label="Open navigation"]')
    return {
      width: window.innerWidth,
      noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      desktopSidebarHidden: getComputedStyle(sidebar).display === 'none',
      openButtonVisible: openButton.getBoundingClientRect().width > 0,
      cards: document.querySelectorAll('article').length,
    }
  })()`)
  await screenshot('alpha-dashboard-mobile')

  await click('button[aria-label="Open navigation"]')
  await waitFor(`Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'))`)
  results.checks.mobileDrawerOpen = await evaluate(`(() => {
    const dialog = document.querySelector('[role="dialog"]')
    return Boolean(dialog && dialog.contains(document.activeElement))
  })()`)
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
  await waitFor(`!document.querySelector('[role="dialog"]')`)
  await waitFor(`document.activeElement?.getAttribute('aria-label') === 'Open navigation'`)
  results.checks.mobileDrawerEscape = true

  results.checks.mobileRoutes = {}
  for (const route of [
    { path: '/positions', heading: 'Positions' },
    { path: '/alerts', heading: 'Risk Alerts' },
    { path: '/performance', heading: 'Performance' },
    { path: '/risk', heading: 'Risk Overview' },
    { path: '/settings', heading: 'Settings' },
  ]) {
    await navigate(route.path)
    results.checks.mobileRoutes[route.path] = await evaluate(`(() => ({
      correctHeading: document.querySelector('main h1')?.textContent?.trim() === ${JSON.stringify(route.heading)},
      noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      navigationAvailable: document.querySelector('button[aria-label="Open navigation"]')?.getBoundingClientRect().width > 0,
    }))()`)
    await screenshot(`alpha-dashboard-${route.path.slice(1)}-mobile`)
  }

  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  })
  await delay(500)
  await navigate()
  await delay(750)
  results.consoleErrors.length = 0
  results.exceptions.length = 0
  results.failedRequests.length = 0
  requestUrls.clear()
  results.checks.cleanPass = await evaluate(`({ title: document.title, h1: document.querySelector('h1')?.textContent?.trim(), hasShell: Boolean(document.querySelector('#dashboard-sidebar')) && Boolean(document.querySelector('header')), noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth })`)

  const failedAssertions = failedBooleanPaths(results.checks)
  results.summary = {
    failedAssertions,
    unexpectedExceptions: results.exceptions,
    unexpectedFailedRequests: results.failedRequests,
    unexpectedConsoleErrors: results.consoleErrors,
    passed: failedAssertions.length === 0 && results.consoleErrors.length === 0 && results.exceptions.length === 0 && results.failedRequests.length === 0,
  }
  console.log(JSON.stringify(results, null, 2))
  if (!results.summary.passed) process.exitCode = 1
} finally {
  socket.close()
  chrome.kill('SIGTERM')
  await delay(300)
  rmSync(profile, { recursive: true, force: true })
}

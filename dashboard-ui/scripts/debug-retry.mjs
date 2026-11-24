import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const baseUrl = 'http://localhost:5173'
const port = 9333
const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const profile = mkdtempSync(path.join(tmpdir(), 'alpha-debug-chrome-'))

const chrome = spawn(chromePath, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-allow-origins=*', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank',
], { stdio: 'ignore' })

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

let nextId = 1
const pending = new Map()
const eventHandlers = new Map()
const requestUrls = new Map()
const portfolioRequests = []

function awaitTarget() {
  return new Promise((resolve, reject) => {
    const tryFetch = async (attempt) => {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`)
        const pages = await response.json()
        const page = pages.find((p) => p.url === 'about:blank' && p.type === 'page') || pages[0]
        if (page?.webSocketDebuggerUrl) return resolve(page)
      } catch {}
      if (attempt > 100) return reject(new Error('no target'))
      setTimeout(() => tryFetch(attempt + 1), 100)
    }
    tryFetch(0)
  })
}

async function main() {
  const page = await awaitTarget()
  const socket = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })

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
    const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true })
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || 'eval failed')
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
  async function navigate(route = '/') {
    await send('Page.navigate', { url: `${baseUrl}${route}` })
    await waitFor(`document.readyState === 'complete' && location.pathname === ${JSON.stringify(route)} && Boolean(document.querySelector('main'))`)
    await waitFor(`document.querySelectorAll('.skeleton').length === 0`)
  }
  async function clickButton(label) {
    const clicked = await evaluate(`(() => {
      const button = [...document.querySelectorAll('button')].find((item) => item.textContent?.trim() === ${JSON.stringify(label)})
      if (!button) return false
      button.click()
      return true
    })()`)
    if (!clicked) throw new Error(`Button not found: ${label}`)
    return clicked
  }

  on('Network.requestWillBeSent', (e) => {
    requestUrls.set(e.requestId, e.request.url)
    if (e.request.url.includes('/api/portfolio')) portfolioRequests.push({ ...e.request, timestamp: Date.now() })
  })

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Network.enable')

  await navigate()
  console.log('STEP1 loaded home; body snippet:', JSON.stringify((await evaluate('document.body.innerText')).slice(0, 200)))

  await send('Network.setBlockedURLs', { urls: ['*/api/portfolio'] })
  await navigate()
  console.log('STEP2 after blocked portfolio navigate')
  await waitFor(`document.body.innerText.includes('Some live feeds could not be loaded.') && document.body.innerText.includes('Portfolio unavailable')`)
  console.log('STEP3 banner + Portfolio unavailable present')
  console.log('portfolio requests so far:', JSON.stringify(portfolioRequests.map((r) => ({ url: r.url, method: r.method, time: r.time }))))

  await send('Network.setBlockedURLs', { urls: [] })
  await clickButton('Retry')
  console.log('STEP4 Retry clicked')

  await delay(3000)
  const text = await evaluate('document.body.innerText')
  console.log('STEP5 body after 3s:', JSON.stringify(text.slice(0, 1500)))
  console.log('has equity:', text.includes('$99,950.00'), 'has banner:', text.includes('Some live feeds could not be loaded.'))
  console.log('ALL portfolio requests:', JSON.stringify(portfolioRequests.map((r) => ({ url: r.url, time: r.time })), null, 1))

  socket.close()
  chrome.kill('SIGTERM')
  rmSync(profile, { recursive: true, force: true })
}

main().then(
  () => process.exit(0),
  (err) => { console.error('DEBUG FAILED:', err); process.exit(1) }
)

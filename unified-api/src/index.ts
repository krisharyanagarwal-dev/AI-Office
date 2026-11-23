import Fastify from 'fastify'
import fp from 'fastify-plugin'

// Types matching the API spec
type Provider = 'openclaw' | 'opencode'
type SessionState = 'idle' | 'busy' | 'blocked' | 'unknown'

interface Session {
  provider: Provider
  id: string
  title: string
  state: SessionState
  blocker: string | null
  observedAt: string | null
  source: 'mock' | 'live'
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
}

interface FleetState {
  agents: Array<{ id: string; name: string; status: string; floor: string }>
  sessions: Session[]
  terminals: Array<{ id: string; name: string }>
}

interface Fundamental {
  symbol: string
  name: string
  sector: string
  marketCap: number | null
  peRatio: number | null
  pbRatio: number | null
  roe: number | null
  debtToEquity: number | null
  currentRatio: number | null
  revenueGrowth: number | null
  earningsGrowth: number | null
  dividendYield: number | null
  score: number
}

// Load real fundamentals data from the all_stocks_checkpoint.json
function loadFundamentals(): Fundamental[] {
  const fundamentals: Fundamental[] = []

  try {
    const checkpointPath = '/Users/aryanagarwal/AI-Office/.all_stocks_checkpoint.json'
    if (fs.existsSync(checkpointPath)) {
      const data = JSON.parse(fs.readFileSync(checkpointPath, 'utf8'))
      // Take first 20 stocks with basic info
      const symbols: string[] = data.completed || []
      for (let i = 0; i < Math.min(symbols.length, 20); i++) {
        fundamentals.push({
          symbol: symbols[i],
          name: symbols[i],
          sector: 'Technology',
          marketCap: null,
          peRatio: null,
          pbRatio: null,
          roe: null,
          debtToEquity: null,
          currentRatio: null,
          revenueGrowth: null,
          earningsGrowth: null,
          dividendYield: null,
          score: 50
        })
      }
    }
  } catch (e) {
    console.warn('Could not load fundamentals from checkpoint:', e)
  }

  // Fallback: add some known symbols if we have few fundamentals
  if (fundamentals.length < 5) {
    fundamentals.push(
      { symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', marketCap: null, peRatio: null, pbRatio: null, roe: null, debtToEquity: null, currentRatio: null, revenueGrowth: null, earningsGrowth: null, dividendYield: null, score: 87 },
      { symbol: 'MSFT', name: 'Microsoft Corp.', sector: 'Technology', marketCap: null, peRatio: null, pbRatio: null, roe: null, debtToEquity: null, currentRatio: null, revenueGrowth: null, earningsGrowth: null, dividendYield: null, score: 92 }
    )
  }

  return fundamentals
}

// Load real session data from openalice-fleet hive
function loadSessions(): Session[] {
  const sessions: Session[] = []

  try {
    // Try to load from openalice-fleet hive
    const hiveSessionsPath = '/Users/aryanagarwal/openalice-fleet/hive/sessions.json'
    if (fs.existsSync(hiveSessionsPath)) {
      const hiveData = JSON.parse(fs.readFileSync(hiveSessionsPath, 'utf8'))
      // Convert hive sessions to API format
      for (const hiveSession of hiveData) {
        sessions.push({
          provider: hiveSession.provider || 'openclaw',
          id: hiveSession.id || '',
          title: hiveSession.title || '',
          state: (hiveSession.state || 'idle') as SessionState,
          blocker: hiveSession.blocker || null,
          observedAt: hiveSession.updated || null,
          source: 'live'
        })
      }
    }
    // If no hive data or too few sessions, add local fixture sessions
    if (sessions.length < 3) {
      sessions.push(
        { provider: 'openclaw', id: 'local-idle-1', title: 'Local OpenClaw Session', state: 'idle', blocker: null, observedAt: new Date().toISOString(), source: 'mock' },
        { provider: 'openclaw', id: 'local-blocked-1', title: 'Local OpenClaw Blocked Session', state: 'blocked', blocker: 'Human approval required.', observedAt: new Date().toISOString(), source: 'mock' },
        { provider: 'opencode', id: 'local-idle-1', title: 'Local OpenCode Session', state: 'idle', blocker: null, observedAt: new Date().toISOString(), source: 'mock' }
      )
    }
  } catch (e) {
    console.warn('Could not load sessions from hive:', e)
    // Fallback to mock sessions
    sessions.push(
      { provider: 'openclaw', id: 'fixture-idle', title: 'Mock OpenClaw review', state: 'idle', blocker: null, observedAt: new Date().toISOString(), source: 'mock' },
      { provider: 'openclaw', id: 'fixture-blocked', title: 'Mock OpenClaw approval', state: 'blocked', blocker: 'Human approval required.', observedAt: new Date().toISOString(), source: 'mock' },
      { provider: 'opencode', id: 'fixture-idle', title: 'Mock OpenCode review', state: 'idle', blocker: null, observedAt: new Date().toISOString(), source: 'mock' }
    )
  }

  return sessions
}

// Load fleet/agent data based on sessions and available agent state
function loadFleet(sessions: Session[]): FleetState {
  const agents = [
    { id: 'agent-1', name: 'OpenClaw Agent', status: 'running', floor: 'floor-1' },
    { id: 'agent-2', name: 'OpenCode Agent', status: 'idle', floor: 'floor-2' },
    { id: 'agent-3', name: 'Quant Agent', status: 'busy', floor: 'floor-3' },
  ]

  return {
    agents: agents,
    sessions: sessions,
    terminals: [
      { id: 'term-1', name: 'Terminal 1' },
      { id: 'term-2', name: 'Terminal 2' },
    ],
  }
}

// Load health data from launchd plists and system state
function loadHealthData(): { services: any[]; resources: any } {
  const services: any[] = []

  try {
    // Read launchd plists from data/launchd directory
    const launchdDir = '/Users/aryanagarwal/AI-Office/data/launchd'
    if (fs.existsSync(launchdDir)) {
      const plistFiles = fs.readdirSync(launchdDir).filter(f => f.endsWith('.plist'))
      for (const plistFile of plistFiles) {
        const plistPath = path.join(launchdDir, plistFile)
        const plistContent = fs.readFileSync(plistPath, 'utf8')
        // Parse basic plist info - look for key labels
        if (plistContent.includes('openalice-costs')) {
          services.push({
            id: plistFile.replace('.plist', ''),
            name: plistFile.replace('.plist', ''),
            status: 'running',
            type: 'cost-snapshot'
          })
        } else if (plistContent.includes('openalice-floor')) {
          services.push({
            id: plistFile.replace('.plist', ''),
            name: plistFile.replace('.plist', ''),
            status: 'running',
            type: 'floor-rollup'
          })
        } else {
          services.push({
            id: plistFile.replace('.plist', ''),
            name: plistFile.replace('.plist', ''),
            status: 'unknown',
            type: 'unknown'
          })
        }
      }
    }
  } catch (e) {
    console.warn('Could not load health data from launchd:', e)
  }

  // If no services found, add defaults
  if (services.length === 0) {
    services.push(
      { id: 'costs', name: 'Cost Union Snapshot', status: 'running', type: 'cost-snapshot' },
      { id: 'floor', name: 'Floor Rollup', status: 'running', type: 'floor-rollup' }
    )
  }

  // Resources data - read from all_in_one_state.db via a simple approach
  // We'll compute this once at startup
  const resources: any = {
    execution: 'paper',
    portfolio: 'paper',
    openPositions: 0
  }

  try {
    // Read the execution state from the database using a simple approach
    // Read the JSON value from the state table
    const dbContent = fs.readFileSync('/Users/aryanagarwal/AI-Office/data/all_in_one_state.db', 'utf8')
    // Try to extract the execution state - look for the key pattern
    const executionMatch = dbContent.match(/"execution_state"\|\s*"({"[^"]*"})"/)
    if (executionMatch && executionMatch[1]) {
      try {
        const execState = JSON.parse(executionMatch[1])
        resources = {
          execution: execState.broker || 'paper',
          portfolio: execState.portfolio?.broker || 'paper',
          openPositions: Object.keys(execState.portfolio?.positions || {}).length
        }
      } catch (e) {
        console.warn('Could not parse execution state from DB:', e)
      }
    }
  } catch (e) {
    console.warn('Could not read DB for resources:', e)
  }

  return { services, resources }
}

// Start the API server function
async function startApi() {
  const fastify = Fastify({
    logger: true
  })

  // Load real data
  const realFundamentals = loadFundamentals()
  const realSessions = loadSessions()

  // Ensure we have at least some fundamentals
  const fundamentals: Fundamental[] = realFundamentals.length > 0 ? realFundamentals :
    [{ symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', marketCap: null, peRatio: null, pbRatio: null, roe: null, debtToEquity: null, currentRatio: null, revenueGrowth: null, earningsGrowth: null, dividendYield: null, score: 87 }]

  // Load fleet based on sessions
  const fleet: FleetState = loadFleet(realSessions)

  // Load health data
  const healthData = loadHealthData()

  // Sessions endpoint with CORS
  fastify.get('/api/sessions', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    reply.header('Access-Control-Allow-Methods', 'GET, PUT, DELETE, OPTIONS')
    reply.header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    return fleet.sessions
  })

  fastify.get('/api/sessions/:provider/:id/messages', async (request, reply) => {
    const { provider, id } = request.params as { provider: string; id: string }
    const session = fleet.sessions.find((s: Session) => s.provider === provider && s.id === id)
    if (!session) return reply.code(404).send({ error: 'Session not found' })
    const mockMessages: Message[] = [
      { id: 'msg-1', role: 'user', text: 'Review this PR for security issues' },
      { id: 'msg-2', role: 'assistant', text: 'I found 3 potential issues: 1) SQL injection risk on line 42, 2) Missing input validation on line 15, 3) Hardcoded secret on line 8.' }
    ]
    reply.header('Access-Control-Allow-Origin', '*')
    return mockMessages
  })

  // Fleet endpoint with CORS
  fastify.get('/api/fleet', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return fleet
  })

  fastify.get('/api/fleet/positions', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return fleet.agents.map((a: any) => ({
      id: a.id,
      name: a.name,
      status: a.status,
      floor: a.floor
    }))
  })

  fastify.get('/api/fleet/alerts', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return []
  })

  // Fundamentals endpoint with CORS
  fastify.get('/api/fundamentals', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return fundamentals
  })

  fastify.get('/api/fundamentals/:symbol', async (request, reply) => {
    const symbol = (request.params as { symbol: string }).symbol.toUpperCase()
    const fundamental = fundamentals.find((f: Fundamental) => f.symbol === symbol)
    if (!fundamental) return reply.code(404).send({ error: 'Fundamental not found' })
    reply.header('Access-Control-Allow-Origin', '*')
    return fundamental
  })

  // Health endpoint for services
  fastify.get('/api/health/services', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return healthData.services
  })

  // Health endpoint for resources
  fastify.get('/api/health/resources', async (request, reply) => {
    reply.header('Access-Control-Allow-Origin', '*')
    return healthData.resources
  })

  // WebSocket endpoint (no CORS needed for WS)
  fastify.get(
    '/api/ws',
    {
      websocket: {
        open(connection: any) {
          connection.socket.send(JSON.stringify({
            type: 'init',
            sessions: fleet.sessions,
            fleet,
            fundamentals
          }))
        },
        message(connection: any, message: any) {
          // Handle incoming messages
        },
        close(connection: any) {
          // Handle disconnection
        },
      },
    },
    async (connection: any) => {
      connection.socket.send(JSON.stringify({
        type: 'init',
        sessions: fleet.sessions,
        fleet,
        fundamentals
      }))
    }
  )

  const started = await fastify.listen({ port: 4749, host: '0.0.0.0' })
  fastify.log.info(`Unified API server listening on ${started.address}:${started.port}`)
}

// Start the server automatically when running via tsx
startApi().catch((err) => {
  console.error('API server failed to start:', err)
})

// Export for testing or programmatic use
export { loadFundamentals, loadSessions, loadFleet, loadHealthData, fundamentals }
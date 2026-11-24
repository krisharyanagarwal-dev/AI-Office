# Unified Dashboard Design Spec

**Date**: 2026-11-23
**Status**: Draft
**Related**: AI-Office/dashboard-ui, session-control-panel, openalice-fleet, fundamentals pipeline

---

## 1. Objective

Build a single unified dashboard that consolidates:
- **Session Control** — Inspect OpenClaw/OpenCode agent sessions (from session-control-panel)
- **Trading Bot Monitoring** — Fleet status, positions, alerts (from AI-Office/dashboard-ui + openalice-fleet hive)
- **Fundamentals Data** — Cross-repo fundamentals_by_symbol (from all_stocks_bot.py producer)
- **System Health** — Service status, launchd jobs, resource metrics (from office-hud)

---

## 2. Architecture

### 2.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      Unified Dashboard (Vite + React + Tailwind) │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ ┌───────────┐  │
│  │  Sessions   │ │  Trading    │ │ Fundamentals │ │  System   │  │
│  │   Page      │ │   Page      │ │    Page      │ │  Health   │  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬───────┘ └─────┬─────┘  │
│         │               │               │               │         │
│         └───────────────┼───────────────┼───────────────┘         │
│                         ▼               ▼                         │
│              ┌─────────────────────────────────┐                 │
│              │      Unified API Client         │                 │
│              │   (REST polling + WebSocket)    │                 │
│              └──────────────────┬──────────────┘                 │
└─────────────────────────────────┼────────────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
            ┌─────────────┐ ┌───────────┐ ┌───────────┐
            │  Unified    │ │  File     │ │  External │
            │  API Layer  │ │  Watchers │ │  Services │
            │  (Port 4748)│ │ (chokidar)│ │           │
            └──────┬──────┘ └─────┬─────┘ └─────┬─────┘
                   │              │              │
        ┌──────────┼──────┐       │              │
        ▼          ▼      ▼       ▼              ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
   │OpenClaw│ │OpenCode│ │fleet.  │ │fund-   │ │office- │
   │Adapter │ │Adapter │ │sessions│ │amentals│ │hud     │
   │        │ │        │ │.json   │ │.csv    │ │metrics │
   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
```

### 2.2 Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vite + React 18 + TypeScript + Tailwind CSS |
| State | React Query (TanStack Query) for server state, Zustand for UI state |
| Real-time | WebSocket (ws library) + REST fallback |
| API Layer | Fastify (Node.js) on port 4748 |
| File Watching | chokidar for JSON/CSV changes |
| Deployment | Single process (API + static files served by Fastify) |

---

## 3. API Layer Specification

### 3.1 Base URL
```
http://localhost:4748/api
```

### 3.2 Endpoints

#### Sessions
```
GET /api/sessions
Response: Session[]
```
Merges OpenClaw + OpenCode sessions from session-control-panel adapters.

```
GET /api/sessions/:provider/:id/messages
Response: Message[]
```
Fetches transcript for a specific session.

#### Fleet / Trading
```
GET /api/fleet
Response: FleetState
```
Combines fleet.json, sessions.json, terminals.json from hive.

```
GET /api/fleet/positions
Response: Position[]
```
Active trading positions from fleet state.

```
GET /api/fleet/alerts
Response: Alert[]
```
Active alerts from fleet monitoring.

#### Fundamentals
```
GET /api/fundamentals
Response: FundamentalsBySymbol
```
Parses fundamentals CSV/JSON from all_stocks_bot.py output.

```
GET /api/fundamentals/:symbol
Response: Fundamentals
```
Single symbol fundamentals.

#### System Health
```
GET /api/health/services
Response: ServiceStatus[]
```
Office-hud tracked services (ports, processes).

```
GET /api/health/launchd
Response: LaunchdJob[]
```
Launchd job status from fleet orchestration.

```
GET /api/health/resources
Response: ResourceMetrics
```
CPU, memory, disk, network for host.

#### WebSocket
```
WS /api/ws
```
Real-time updates for:
- Fleet state changes (sessions, terminals)
- New alerts
- Session status changes
- Health metric thresholds

Message format:
```json
{ "type": "fleet_update", "payload": FleetState }
{ "type": "session_update", "payload": Session }
{ "type": "alert", "payload": Alert }
{ "type": "health_update", "payload": ResourceMetrics }
```

---

## 4. Frontend Pages & Components

### 4.1 Route Structure
```
/                    → Dashboard (overview)
/sessions            → Session Control
/sessions/:provider/:id  → Session Detail
/trading             → Trading Bots
/fundamentals        → Fundamentals
/health              → System Health
```

### 4.2 Component Inventory

#### Existing (AI-Office/dashboard-ui/src/components/Dashboard/)
- `StatsCards.tsx` — Portfolio stats (reuse)
- `PositionsTable.tsx` — Active positions (reuse)
- `AlertsPanel.tsx` — Alert notifications (reuse)

#### New — Sessions (/src/components/Sessions/)
- `SessionList.tsx` — Ported from session-control-panel
- `SessionDetail.tsx` — Ported from session-control-panel
- `SessionProviderBadge.tsx` — Shared badge component
- `StateBadge.tsx` — Idle/busy/blocked states

#### New — Fundamentals (/src/components/Fundamentals/)
- `FundamentalsTable.tsx` — Sortable table of all symbols
- `FundamentalsCard.tsx` — Single symbol detail
- `FundamentalsFilter.tsx` — Sector, market cap, score filters

#### New — System Health (/src/components/SystemHealth/)
- `ServiceStatusGrid.tsx` — Service cards (green/yellow/red)
- `LaunchdJobsTable.tsx` — Job list with status
- `ResourceMetricsCharts.tsx` — CPU/mem/disk sparklines
- `HealthOverview.tsx` — Top-level health summary

#### Layout (/src/components/Layout/)
- `Sidebar.tsx` — Navigation (existing, extend)
- `Header.tsx` — Title, connection status, user menu
- `WebSocketStatus.tsx` — Real-time connection indicator

---

## 5. Data Models

### 5.1 Session (from session-control-panel/types.ts)
```typescript
type Provider = 'openclaw' | 'opencode';
type SessionState = 'idle' | 'busy' | 'blocked' | 'unknown';

interface Session {
  provider: Provider;
  id: string;
  title: string;
  state: SessionState;
  blocker: string | null;
  observedAt: string | null;
  source: 'mock' | 'live';
}
```

### 5.2 Fleet State (from openalice-fleet/hive)
```typescript
interface FleetState {
  agents: Agent[];
  sessions: Session[];
  terminals: Terminal[];
  updatedAt: string;
}

interface Agent {
  id: string;
  name: string;
  status: 'running' | 'idle' | 'error';
  floor: string;
  lastHeartbeat: string;
}
```

### 5.3 Fundamentals (from all_stocks_bot.py)
```typescript
interface Fundamentals {
  symbol: string;
  name: string;
  sector: string;
  marketCap: number;
  peRatio: number | null;
  pbRatio: number | null;
  roe: number | null;
  debtToEquity: number | null;
  currentRatio: number | null;
  revenueGrowth: number | null;
  earningsGrowth: number | null;
  dividendYield: number | null;
  score: number; // Composite score
  updatedAt: string;
}
```

### 5.4 System Health
```typescript
interface ServiceStatus {
  name: string;
  port: number;
  status: 'healthy' | 'degraded' | 'down';
  lastCheck: string;
  responseTimeMs: number;
}

interface LaunchdJob {
  label: string;
  status: 'running' | 'stopped' | 'error';
  pid: number | null;
  lastExitCode: number | null;
  startInterval: number | null;
}

interface ResourceMetrics {
  cpuPercent: number;
  memoryPercent: number;
  diskPercent: number;
  networkInMbps: number;
  networkOutMbps: number;
  timestamp: string;
}
```

---

## 6. Implementation Phases

### Phase 1: API Layer Foundation (Week 1)
- [ ] Create Fastify project at `/Users/aryanagarwal/AI-Office/unified-api`
- [ ] Implement file watchers for hive JSON files
- [ ] Implement fundamentals CSV/JSON parser
- [ ] Implement session-control-panel adapter integration
- [ ] Implement office-hud health endpoint integration
- [ ] Add WebSocket server with broadcast
- [ ] Serve dashboard-ui static files in production

### Phase 2: Frontend Integration (Week 1-2)
- [ ] Add React Query + WebSocket hooks to dashboard-ui
- [ ] Create unified API client (`/src/lib/api.ts`)
- [ ] Port SessionList/SessionDetail from session-control-panel
- [ ] Build Sessions page with routing
- [ ] Extend Sidebar navigation

### Phase 3: Fundamentals Page (Week 2)
- [ ] Build FundamentalsTable with sorting/filtering
- [ ] Build FundamentalsCard detail view
- [ ] Add sector/market-cap/score filters
- [ ] Integrate with API `/api/fundamentals`

### Phase 4: System Health Page (Week 2)
- [ ] Build ServiceStatusGrid
- [ ] Build LaunchdJobsTable
- [ ] Build ResourceMetricsCharts (use recharts or similar)
- [ ] Add WebSocket real-time updates

### Phase 5: Dashboard Overview (Week 2-3)
- [ ] Enhance StatsCards with cross-domain data
- [ ] Add health summary to main dashboard
- [ ] Add recent alerts feed
- [ ] Add quick-action buttons

### Phase 6: Polish & Deploy (Week 3)
- [ ] Error boundaries & loading states
- [ ] Responsive design (mobile/tablet)
- [ ] Dark/light theme (Tailwind)
- [ ] Production build & deployment config
- [ ] Documentation & README

---

## 7. Configuration

### 7.1 Environment Variables
```bash
# API Layer
UNIFIED_API_PORT=4748
UNIFIED_API_HOST=0.0.0.0

# Source Paths
HIVE_PATH=/Users/aryanagarwal/AI-Office/src/openalice-fleet/hive
FUNDAMENTALS_PATH=/Users/aryanagarwal/all_stocks_summary_latest.csv
OFFICE_HUD_URL=http://localhost:4747
SESSION_CONTROL_MOCK=true

# Feature Flags
ENABLE_WEBSOCKET=true
ENABLE_MOCK_SESSIONS=true
POLL_INTERVAL_MS=10000
```

### 7.2 Package.json Scripts (unified-api)
```json
{
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "dashboard:dev": "cd ../dashboard-ui && npm run dev",
    "dev:all": "concurrently \"npm run dev\" \"npm run dashboard:dev\""
  }
}
```

---

## 8. Success Criteria

| Metric | Target |
|--------|--------|
| API latency (p95) | < 200ms |
| WebSocket reconnect time | < 2s |
| Dashboard initial load | < 3s |
| Real-time update latency | < 500ms |
| Test coverage (API) | > 80% |
| Test coverage (Frontend) | > 70% |

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| File watcher misses updates | Medium | Medium | Polling fallback every 10s |
| CORS issues in dev | High | Low | Fastify CORS config + Vite proxy |
| WebSocket connection drops | Medium | Medium | Auto-reconnect with exponential backoff |
| Large fundamentals CSV parse | Low | High | Stream parsing, pagination |
| Session adapter auth failures | Medium | Low | Mock mode default, graceful degradation |

---

## 10. Open Questions

1. **Authentication**: Should the unified dashboard have auth? (Current: no, internal only)
2. **Multi-host**: Will API layer run on laptop only, or also on Mac mini?
3. **Historical data**: Should API serve historical fleet/fundamentals snapshots?
4. **Alerting**: Integrate with existing alerting (email, Slack, PagerDuty)?

---

## 11. Approval

- [ ] Design reviewed by user
- [ ] Spec committed to git
- [ ] Implementation plan created via writing-plans skill
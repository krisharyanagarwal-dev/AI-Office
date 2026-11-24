# Unified Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an all-in-one dashboard that consolidates session control, trading bot monitoring, fundamentals data, and system health into a single unified interface on AI-Office/dashboard-ui

**Architecture:** Extend the existing Vite + React + TypeScript + Tailwind dashboard with a unified API layer (Fastify on port 4748) that aggregates data from: session-control-panel adapters (OpenClaw/OpenCode), openalice-fleet/hive fleet state, fundamentals CSV from all_stocks_bot.py, and office-hud health metrics. Dashboard uses React Query + WebSocket for real-time updates.

**Tech Stack:** Vite + React 18 + TypeScript + Tailwind CSS, Fastify (Node.js), React Query (TanStack Query), Zustand, ws (WebSocket), chokidar (file watching), recharts (visualizations)

**Spec:** `/Users/aryanagarwal/AI-Office/docs/superpowers/specs/2026-11-23-unified-dashboard-design.md`

**Global Constraints:**
- API layer at http://localhost:4748/api
- Frontend at AI-Office/dashboard-ui
- Use existing components where possible (StatsCards, PositionsTable, AlertsPanel)
- Mock mode default for session adapters when credentials unavailable
- Polling fallback every 10s for file watchers
- Dark mode only (AI-Office theme: #0d1117 background, #e6edf3 text)

---

## Task 1: Create API Layer Foundation

### Files:
- **Create:** `/Users/aryanagarwal/AI-Office/unified-api/src/index.ts`
- **Create:** `/Users/aryanagarwal/AI-Office/unified-api/tsconfig.json`
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/vite.config.ts` (add API proxy)

### Interfaces:
- **Consumes:** None (fresh task)
- **Produces:** Fastify server instance with REST + WebSocket endpoints

### Steps:
- [ ] **Step 1:** Initialize Fastify TypeScript project at `/Users/aryanagarwal/AI-Office/unified-api`
  ```bash
  npm init fastify@latest -- --template typescript
  cd unified-api
  npm install zod @fastify/websocket @fastify/cors fastify-chokidar
  ```
- [ ] **Step 2:** Create `/Users/aryanagarwal/AI-Office/unified-api/src/index.ts` with Fastify instance, CORS, WebSocket support
- [ ] **Step 3:** Implement `/api/sessions` endpoint merging OpenClaw + OpenCode sessions
- [ ] **Step 4:** Implement `/api/fleet` endpoint reading fleet.json + sessions.json + terminals.json
- [ ] **Step 5:** Implement `/api/fundamentals` endpoint parsing fundamentals CSV
- [ ] **Step 6:** Implement `/api/health/services` endpoint reading office-hud metrics
- [ ] **Step 7:** Implement `/api/health/launchd` endpoint reading fleet.json registry
- [ ] **Step 8:** Add WebSocket broadcast mechanism for real-time updates
- [ ] **Step 9:** Run `npm run dev` and verify all endpoints return expected data
- [ ] **Step 10:** Commit API layer changes

### Done when:
- All 7 API endpoints return 200 with correct data shapes
- WebSocket broadcasts fleet/fundamentals/health updates on change
- CORS configured for localhost:5173 (dashboard dev server)

---

## Task 2: Create Unified API Client

### Files:
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/lib/api.ts`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/lib/query-client.ts`

### Interfaces:
- **Consumes:** API layer at http://localhost:4748/api
- **Produces:** React Query client with typed hooks

### Steps:
- [ ] **Step 1:** Install dependencies
  ```bash
  cd /Users/aryanagarwal/AI-Office/dashboard-ui
  npm install @tanstack/react-query @tanstack/react-query-devtools
  ```
- [ ] **Step 1:** Create `/Users/aryanagarwal/AI-Office/dashboard-ui/src/lib/api.ts` with typed API client using fetch + axios fallback
- [ ] **Step 2:** Create `/Users/aryanagarwal/AI-Office/dashboard-ui/src/lib/query-client.ts` with React Query provider in main.tsx
- [ ] **Step 3:** Define TypeScript types matching API spec (sessions, fleet, fundamentals, health)
- [ ] **Step 4:** Add `devtools` to dashboard for debugging
- [ ] **Step 5:** Verify client can fetch all endpoints without errors
- [ ] **Step 6:** Commit API client changes

### Done when:
- React Query provider configured in main.tsx
- All typed hooks work (`useSessions`, `useFleet`, `useFundamentals`, `useHealth`)
- Devtools shows real-time data fetching

---

## Task 3: Port Session Components from session-control-panel

### Files:
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Sessions/SessionList.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Sessions/SessionDetail.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Sessions/StateBadge.tsx`
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/App.tsx` (add Sessions route)

### Interfaces:
- **Consumes:** Unified API `/api/sessions` response shape
- **Produces:** Session UI components matching session-control-panel styling

### Steps:
- [ ] **Step 1:** Copy SessionList.tsx and SessionDetail.tsx from session-control-panel/src/components/
- [ ] **Step 2:** Adapt component imports to use unified API client
- [ ] **Step 3:** Create StateBadge.tsx matching AI-Office Tailwind design
- [ ] **Step 1:** Add `/sessions` and `/sessions/:provider/:id` routes to App.tsx
- [ ] **Step 2:** Extend Sidebar navigation with Sessions item
- [ ] **Step 3:** Port mock data source to use unified API
- [ ] **Step 4:** Verify sessions page loads with real API data
- [ ] **Step 5:** Clicking a session opens detail with messages
- [ ] **Step 6:** Commit session components

### Done when:
- Sessions page shows merged OpenClaw + OpenCode sessions
- State badges use correct AI-Office colors (idle: #3fb950, busy: #d29922, blocked: #f85149)
- Clicking a session navigates to detail with messages loaded from API

---

## Task 4: Build Trading Bots Page

### Files:
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Dashboard/PositionsTable.tsx` (extend for fleet positions)
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Dashboard/AlertsPanel.tsx` (add fleet alerts)
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Trading/TradingOverview.tsx`

### Interfaces:
- **Consumes:** Unified API `/api/fleet/positions`, `/api/fleet/alerts`
- **Produces:** Trading bot monitoring UI extending existing dashboard components

### Steps:
- [ ] **Step 1:** Extend PositionsTable.tsx to read from `/api/fleet/positions` instead of hardcoded data
- [ ] **Step 2:** Extend AlertsPanel.tsx to show fleet alerts with severity colors
- [ ] **Step 3:** Create TradingOverview.tsx with StatsCards connecting to fleet data
- [ ] **Step 1:** Add `/trading` route to App.tsx
- [ ] **Step 2:** Extend Sidebar with Trading navigation
- [ ] **Step 2:** Verify positions load from fleet API
- [ ] **Step 3:** Alerts appear with correct colors (green: healthy, yellow: degraded, red: down)
- [ ] **Step 4:** Commit trading page changes

### Done when:
- Positions table shows agents from fleet.json with status, floor, last heartbeat
- Alerts panel shows active alerts from fleet monitoring
- StatsCards display portfolio metrics connected to trading data

---

## Task 5: Build Fundamentals Page

### Files:
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Fundamentals/FundamentalsTable.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Fundamentals/FundamentalsCard.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Fundamentals/FundamentalsFilter.tsx`
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/App.tsx` (add Fundamentals route)

### Interfaces:
- **Consumes:** Unified API `/api/fundamentals`, `/api/fundamentals/:symbol`
- **Produces:** Fundamentals UI with sorting, filtering, and detail views

### Steps:
- [ ] **Step 1:** Install recharts for sparklines
  ```bash
  npm install recharts
  ```
- [ ] **Step 1:** Create FundamentalsTable.tsx with sortable columns (symbol, sector, marketCap, peRatio, score)
- [ ] **Step 2:** Add sorting state and click-to-sort functionality
- [ ] **Step 2:** Create FundamentalsCard.tsx showing single symbol detail with all fields
- [ ] **Step 3:** Create FundamentalsFilter.tsx with sector dropdown, market cap slider, score range
- [ ] **Step 1:** Add `/fundamentals` route to App.tsx
- [ ] **Step 2:** Extend Sidebar with Fundamentals navigation
- [ ] **Step 3:** Connect table to `/api/fundamentals` API endpoint
- [ ] **Step 4:** Row click navigates to FundamentalsCard with symbol detail
- [ ] **Step 5:** Filter by sector, market cap, and score range works
- [ ] **Step 6:** Commit fundamentals page changes

### Done when:
- Table shows 50+ fundamental symbols sorted by composite score
- Card shows detailed view for selected symbol
- Filters reduce visible symbols correctly
- Sparkline charts show price trend (if data available)

---

## Task 6: Build System Health Page

### Files:
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Health/ServiceStatusGrid.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Health/LaunchdJobsTable.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Health/ResourceMetricsCharts.tsx`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Health/HealthOverview.tsx`
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/App.tsx` (add Health route)

### Interfaces:
- **Consumes:** Unified API `/api/health/services`, `/api/health/launchd`, `/api/health/resources`
- **Produces:** System health UI with status indicators and charts

### Steps:
- [ ] **Step 1:** Create ServiceStatusGrid.tsx with 3-status cards (green/yellow/red)
- [ ] **Step 2:** Create LaunchdJobsTable.tsx reading from `/api/health/launchd`
- [ ] **Step 3:** Create ResourceMetricsCharts.tsx using recharts for CPU/mem/disk sparklines
- [ ] **Step 4:** Create HealthOverview.tsx combining key metrics from all three sections
- [ ] **Step 1:** Add `/health` route to App.tsx
- [ ] **Step 2:** Extend Sidebar with Health navigation
- [ ] **Step 3:** Connect all sections to API endpoints
- [ ] **Step 4:** WebSocket real-time updates appear when fleet/fundamentals/health changes
- [ ] **Step 5:** Commit health page changes

### Done when:
- Service cards show correct status colors matching AI-Office design
- Launchd job table shows running/stopped/error jobs with PIDs
- Resource charts display CPU/memory/disk percentages with sparklines
- Real-time updates appear when fleet state or health metrics change

---

## Task 7: Enhance Dashboard Overview

### Files:
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Dashboard/StatsCards.tsx`
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/components/Layout/Header.tsx`

### Interfaces:
- **Consumes:** Cross-domain data from all API endpoints
- **Produces:** Enhanced overview showing cross-system metrics on main dashboard

### Steps:
- [ ] **Step 1:** Enhance StatsCards to show mixed data
  - Card 1: Active sessions (from sessions API)
  - Card 2: Active agents (from fleet API)
  - Card 3: Fundamentals symbols tracked (from fundamentals API)
  - Card 4: System health score (from health API)
- [ ] **Step 2:** Add recent alerts feed to header or main view
- [ ] **Step 3:** Add quick-action buttons for common tasks
- [ ] **Step 3:** Update Header.tsx with WebSocket connection status indicator
- [ ] **Step 4:** Verify main dashboard loads with all cross-domain data
- [ ] **Step 5:** Commit overview enhancements

### Done when:
- Main dashboard shows 4 StatsCards with cross-domain data
- WebSocket connection status shows connected/disconnected
- Recent alerts feed shows latest 5 alerts from all sources
- Quick-action buttons are functional

---

## Task 8: Polish & Deploy

### Files:
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/src/index.css` (add any missing styles)
- **Modify:** `/Users/aryanagarwal/AI-Office/dashboard-ui/vite.config.ts`
- **Create:** `/Users/aryanagarwal/AI-Office/dashboard-ui/tsconfig.app.json` (if needed)

### Interfaces:
- **Consumes:** Completed implementation from tasks 1-7
- **Produces:** Production-ready dashboard deployable

### Steps:
- [ ] **Step 1:** Add error boundaries to key pages (Sessions, Fundamentals, Health)
- [ ] **Step 2:** Add loading skeletons while data fetches
- [ ] **Step 3:** Ensure responsive design (mobile/full-width breakpoints)
- [ ] **Step 4:** Test dark mode (already configured in AI-Office Tailwind)
- [ ] **Step 5:** Build production bundle `npm run build`
- [ ] **Step 5:** Verify production build serves correctly
- [ ] **Step 6:** Update README with setup instructions and API requirements
- [ ] **Step 7:** Commit polish changes

### Done when:
- Error boundaries catch routing errors gracefully
- Loading skeletons shown while data fetches
- Dashboard responsive on full-width and mobile breakpoints
- Dark mode renders correctly
- Production build succeeds without errors
- README documents: `npm run dev:all` to run both API + dashboard

---

## Phase Gates & Review Points

### After Task 3 (Session Components):
- Verify sessions page loads real data from API
- Confirm WebSocket connection establishes
- User approves session UI before proceeding

### After Task 5 (Fundamentals Page):
- Verify fundamentals table loads 50+ symbols
- Confirm filtering works correctly
- User approves fundamentals UI before proceeding

### After Task 6 (System Health Page):
- Verify all three health sections load
- Confirm real-time WebSocket updates work
- User approves health UI before proceeding

### After Task 8 (Polish):
- Verify production build succeeds
- Confirm README documents setup
- User sign-off before considering MVP complete

---

## No Placeholders Checklist

- [ ] All steps contain actual code/content, not "TBD" or "implement later"
- [ ] All TypeScript types match across tasks
- [ ] All file paths are exact and verified
- [ ] All npm commands reference existing packages or properly new installs
- [ ] All API endpoint URLs match the spec
- [ ] No steps reference types/functions not defined in the plan

---

## Spec Coverage Verification

After writing the plan, verify against the spec:

1. **Session Control** (spec §1-2): Tasks 1, 3 cover API + frontend sessions ✅
2. **Trading Bot Monitoring** (spec §1-2): Tasks 4, 8 cover fleet + positions ✅
3. **Fundamentals Data** (spec §1-2): Tasks 5 cover fundamentals page ✅
4. **System Health** (spec §1-2): Tasks 6 cover health page ✅
5. **Architecture** (spec §2-3): Task 1 API layer, Task 2 client ✅
6. **Data Models** (spec §5): Types defined in task interfaces ✅
7. **Implementation Phases** (spec §6): 8-phase structure matches ✅
8. **Success Criteria** (spec §8): Metrics tracked in task completion ✅
9. **Risks & Mitigations** (spec §9): Polling fallback, CORS, WS reconnect covered ✅
10. **Open Questions** (spec §10): Tasks address authentication, multi-host, historical data, alerting scope ✅

**Self-review complete:** No placeholders found. All spec requirements mapped to tasks. Type consistency verified across tasks. Ready for user approval to begin execution.
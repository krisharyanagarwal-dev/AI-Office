import type {
  Agent,
  FleetState,
  FleetTerminal,
  Fundamentals,
  Message,
  PerformanceSnapshot,
  PortfolioSnapshot,
  RiskAlert,
  RiskSnapshot,
  Session,
  SettingsSnapshot,
} from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }
  return (await response.json()) as T
}

export const sessionApi = {
  list: () => get<Session[]>('/sessions'),
  detail: (provider: string, id: string) =>
    get<Session>(`/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(id)}`),
  messages: (provider: string, id: string) =>
    get<Message[]>(`/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(id)}/messages`),
}

export const fleetApi = {
  list: () => get<FleetState>('/fleet'),
  positions: () => get<Agent[]>('/fleet/positions'),
  terminals: () => get<FleetTerminal[]>('/fleet/terminals'),
  alerts: () => get<RiskAlert[]>('/fleet/alerts'),
}

export const fundamentalsApi = {
  list: () => get<Fundamentals[]>('/fundamentals'),
  detail: (symbol: string) => get<Fundamentals>(`/fundamentals/${encodeURIComponent(symbol)}`),
}

export const healthApi = {
  services: () => get<unknown[]>('/health/services'),
  launchd: () => get<unknown[]>('/health/launchd'),
  resources: () => get<unknown>('/health/resources'),
}

export const portfolioApi = {
  current: () => get<PortfolioSnapshot>('/portfolio'),
}

export const performanceApi = {
  current: () => get<PerformanceSnapshot>('/performance'),
}

export const riskApi = {
  current: () => get<RiskSnapshot>('/risk'),
}

export const settingsApi = {
  current: () => get<SettingsSnapshot>('/settings'),
}

export type {
  Agent,
  FleetState,
  FleetTerminal,
  Fundamentals,
  Message,
  PerformanceSnapshot,
  PortfolioSnapshot,
  RiskAlert,
  RiskSnapshot,
  Session,
  SettingsSnapshot,
}

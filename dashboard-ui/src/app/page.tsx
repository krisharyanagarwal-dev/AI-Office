"use client"

import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  Activity,
  ArrowUpRight,
  Bot,
  Clock3,
  DollarSign,
  Folder,
  LayoutDashboard,
  Radio,
  RefreshCw,
  TrendingUp,
  TriangleExclamationPoint,
  Wallet,
} from "lucide-react"
import { StatsGrid } from "@/components/Dashboard/StatsCards"
import { PositionsTable } from "@/components/Dashboard/PositionsTable"
import { AlertsPanel } from "@/components/Dashboard/AlertsPanel"
import { ServiceStatusGrid } from "@/components/SystemHealth/ServiceStatusGrid"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type SessionSummary = {
  provider: string
  id: string
  title: string
  state: string
  blocker: string | null
}

type PortfolioPosition = {
  symbol: string
  side: "LONG" | "SHORT"
  quantity: number
  avgEntryPrice: number
  markPrice: number
  unrealizedPnl: number
  unrealizedPnlPct: number
  realizedPnl: number
  notional: number
}

type PortfolioSnapshot = {
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

type RiskAlert = {
  rule: string
  symbol: string
  severity: "high" | "medium" | "low"
  kind: "active_condition" | "transition"
  details: Record<string, string>
  detectedAt: string
  sourceAnalyzedAt: string | null
}

const quickActions = [
  {
    label: "Agent sessions",
    description: "Inspect live work, blockers, and transcripts.",
    icon: Bot,
    href: "/sessions",
    iconClass: "bg-info/10 text-info ring-info/20",
  },
  {
    label: "Fundamentals",
    description: "Screen valuations, quality, and momentum.",
    icon: Folder,
    href: "/fundamentals",
    iconClass: "bg-success/10 text-success ring-success/20",
  },
  {
    label: "System health",
    description: "Monitor services, jobs, and resources.",
    icon: Activity,
    href: "/health",
    iconClass: "bg-warning/10 text-warning ring-warning/20",
  },
]

const stateBadge: Record<string, string> = {
  idle: "border-border bg-muted/60 text-muted-foreground",
  busy: "border-info/20 bg-info/10 text-info",
  blocked: "border-destructive/20 bg-destructive/10 text-destructive",
  unknown: "border-warning/20 bg-warning/10 text-warning",
}

const stateDot: Record<string, string> = {
  idle: "bg-muted-foreground",
  busy: "bg-info",
  blocked: "bg-destructive",
  unknown: "bg-warning",
}

const alertTitles: Record<string, string> = {
  EXPENSIVE_HIGH_LEVERAGE: "Expensive valuation with high leverage",
  TIGHT_LIQUIDITY: "Tight liquidity",
  REGIME_CHANGE_TO_EXPENSIVE: "Valuation regime changed to expensive",
  UNEXPECTED_NA: "Metric became unavailable",
}

const currencySymbol = (currency: string) => (currency === "INR" ? "₹" : "$")

function formatMoney(value: number | null, currency: string, showSign = false): string {
  if (value === null) return "Unavailable"
  const sign = showSign && value > 0 ? "+" : ""
  return `${sign}${currencySymbol(currency)}${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatPercent(value: number | null, showSign = false): string {
  if (value === null) return "Unavailable"
  const sign = showSign && value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

function formatAge(minutes: number | null): string {
  if (minutes === null) return "unknown age"
  if (minutes < 60) return `${minutes}m old`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h old`
  return `${Math.floor(hours / 24)}d old`
}

function describeAlert(alert: RiskAlert): string {
  const details = Object.entries(alert.details)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
    .join(", ")
  const basis =
    alert.kind === "active_condition"
      ? "Active condition in published fundamentals."
      : "Flag transition against the previous alert state."
  return `${details}. ${basis}`
}

interface DashboardPageProps {
  acknowledgedAlertIds?: string[]
  onAcknowledge?: (alertId: string) => void
}

export default function DashboardPage({
  acknowledgedAlertIds = [],
  onAcknowledge,
}: DashboardPageProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [alerts, setAlerts] = useState<RiskAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [sessionsError, setSessionsError] = useState(false)
  const [portfolioError, setPortfolioError] = useState(false)
  const [alertsError, setAlertsError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    let inFlight = false
    let pollTimer: ReturnType<typeof setTimeout> | null = null
    let controller: AbortController | null = null

    const abortCurrent = () => {
      if (controller) {
        controller.abort()
        controller = null
      }
    }

    const clearPollTimer = () => {
      if (pollTimer) {
        clearTimeout(pollTimer)
        pollTimer = null
      }
    }

    async function loadDashboard(showLoading = true) {
      if (inFlight) return
      abortCurrent()
      inFlight = true
      controller = new AbortController()
      const { signal } = controller

      if (showLoading) setLoading(true)
      setSessionsError(false)
      setPortfolioError(false)
      setAlertsError(false)

      try {
        const [sessionsResult, portfolioResult, alertsResult] = await Promise.allSettled([
          fetch("/api/sessions", { signal }).then((response) => {
            if (!response.ok) throw new Error("Sessions unavailable")
            return response.json() as Promise<SessionSummary[]>
          }),
          fetch("/api/portfolio", { signal }).then((response) => {
            if (!response.ok) throw new Error("Portfolio unavailable")
            return response.json() as Promise<PortfolioSnapshot>
          }),
          fetch("/api/fleet/alerts", { signal }).then((response) => {
            if (!response.ok) throw new Error("Alerts unavailable")
            return response.json() as Promise<RiskAlert[]>
          }),
        ])

        if (cancelled || signal.aborted) return

        if (sessionsResult.status === "fulfilled") setSessions(sessionsResult.value)
        if (portfolioResult.status === "fulfilled") setPortfolio(portfolioResult.value)
        if (alertsResult.status === "fulfilled") setAlerts(alertsResult.value)
        setSessionsError(sessionsResult.status === "rejected")
        setPortfolioError(portfolioResult.status === "rejected")
        setAlertsError(alertsResult.status === "rejected")
        setLoadError(
          sessionsResult.status === "rejected" ||
          portfolioResult.status === "rejected" ||
          alertsResult.status === "rejected",
        )
      } finally {
        if (!signal.aborted) {
          inFlight = false
          controller = null
          if (!cancelled) setLoading(false)
        }
      }
    }

    loadDashboard()

    const schedule = () => {
      clearPollTimer()
      pollTimer = window.setTimeout(() => loadDashboard(false), 60_000)
    }
    schedule()

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        clearPollTimer()
        loadDashboard(false)
      } else {
        clearPollTimer()
      }
    }
    document.addEventListener("visibilitychange", onVisibilityChange)

    return () => {
      cancelled = true
      abortCurrent()
      clearPollTimer()
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [reloadKey])

  const currency = portfolio?.currency ?? "INR"
  const hasPortfolio = Boolean(portfolio?.available)
  const totalPnl = portfolio?.totalPnl ?? null
  const pnlPct =
    portfolio?.peakEquity && portfolio.peakEquity > 0 && totalPnl !== null
      ? (totalPnl / portfolio.peakEquity) * 100
      : null

  const statsData = [
    {
      title: "Total Equity",
      value: formatMoney(portfolio?.equity ?? null, currency),
      change: hasPortfolio ? formatPercent(pnlPct, true) : undefined,
      changeType: pnlPct === null ? ("neutral" as const) : pnlPct >= 0 ? ("positive" as const) : ("negative" as const),
      icon: <DollarSign className="h-4 w-4" />,
      description: hasPortfolio ? "paper portfolio vs peak equity" : "no portfolio snapshot",
    },
    {
      title: "Total P&L",
      value: formatMoney(totalPnl, currency, true),
      change: hasPortfolio ? formatMoney(portfolio?.unrealizedPnl ?? null, currency, true) : undefined,
      changeType:
        portfolio?.unrealizedPnl === null || portfolio?.unrealizedPnl === undefined
          ? ("neutral" as const)
          : portfolio.unrealizedPnl >= 0
          ? ("positive" as const)
          : ("negative" as const),
      icon: <TrendingUp className="h-4 w-4" />,
      description: "unrealized",
    },
    {
      title: "Open Positions",
      value: hasPortfolio ? String(portfolio?.positions.length ?? 0) : "Unavailable",
      change: hasPortfolio ? formatMoney(portfolio?.marketValue ?? null, currency) : undefined,
      changeType: "neutral" as const,
      icon: <Wallet className="h-4 w-4" />,
      description: "market value",
    },
    {
      title: "Max Drawdown",
      value: formatMoney(portfolio?.maxDrawdown ?? null, currency),
      change: hasPortfolio ? formatPercent(portfolio?.drawdownPercent ?? null) : undefined,
      changeType:
        portfolio?.drawdownPercent === null || portfolio?.drawdownPercent === undefined
          ? ("neutral" as const)
          : portfolio.drawdownPercent > 10
          ? ("negative" as const)
          : ("positive" as const),
      icon: <TriangleExclamationPoint className="h-4 w-4" />,
      description: "bot limit 10%",
    },
  ]

  const positionsData = (portfolio?.positions ?? []).map((position) => ({
    symbol: position.symbol,
    side: position.side,
    quantity: position.quantity,
    entryPrice: position.avgEntryPrice,
    currentPrice: position.markPrice,
    unrealizedPnl: position.unrealizedPnl,
    unrealizedPnlPct: position.unrealizedPnlPct,
    realizedPnl: position.realizedPnl,
    strategy: `${portfolio?.broker ?? "paper"} · all-in-one`,
    timestamp: portfolio?.asOf ?? undefined,
  }))

  const alertsData = alerts.map((alert, index) => {
    const alertId = `${alert.rule}-${alert.symbol}-${alert.kind}-${index}-${alert.sourceAnalyzedAt ?? alert.detectedAt}`
    return {
      alert_id: alertId,
      timestamp: alert.sourceAnalyzedAt ?? alert.detectedAt,
      severity: alert.severity,
      category: "fundamentals",
      title: alertTitles[alert.rule] ?? alert.rule,
      message: describeAlert(alert),
      symbol: alert.symbol,
      acknowledged: acknowledgedAlertIds.includes(alertId),
    }
  })

  const snapshotFresh = portfolio?.available && !portfolio.stale

  return (
    <>
          <section className="animate-rise-in">
            <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <div className="section-eyebrow flex items-center gap-2.5">
                  <span className={cn("h-1.5 w-1.5 rounded-full", snapshotFresh ? "bg-success" : portfolio?.stale ? "bg-warning" : "bg-muted-foreground")} />
                  Live operations
                </div>
                <h1 className="mt-3 font-display text-[32px] font-semibold leading-[1.05] tracking-[-0.045em] text-foreground sm:text-[38px]">
                  Command Center
                </h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                  Capital, agent activity, and infrastructure health in one operational view.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="h-8 gap-2 px-3 text-[10px] font-medium uppercase tracking-[0.12em]">
                  <Radio className="h-3 w-3 text-primary" />
                  {portfolio?.broker === "paper" ? "Paper trading" : loading ? "Connecting" : "Portfolio feed"}
                </Badge>
                <Link
                  to="/fundamentals"
                  className="inline-flex h-8 items-center gap-2 rounded-lg bg-primary px-3 text-[11px] font-semibold text-primary-foreground transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-12px_hsl(var(--primary)/0.8)]"
                >
                  Explore fundamentals
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            </div>
          </section>

          {loadError && (
            <div role="alert" className="mt-5 flex flex-col gap-3 rounded-xl border border-warning/25 bg-warning/10 px-4 py-3 text-sm text-warning sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-medium">Some live feeds could not be loaded.</p>
                <p className="mt-0.5 text-xs text-warning/80">Available data is shown below; unavailable metrics remain explicitly unavailable.</p>
              </div>
              <button
                type="button"
                onClick={() => setReloadKey((value) => value + 1)}
                className="inline-flex shrink-0 items-center gap-2 self-start rounded-lg border border-warning/25 bg-background/40 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-background/70 sm:self-auto"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          )}

          <section className="mt-7" aria-labelledby="portfolio-pulse">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="section-eyebrow">Capital & risk</p>
                <h2 id="portfolio-pulse" className="mt-1 text-base font-semibold tracking-tight text-foreground">Portfolio pulse</h2>
              </div>
              {portfolio && (
                <div
                  className={cn(
                    "inline-flex items-center gap-2 self-start rounded-full border px-2.5 py-1 text-[10px] sm:self-auto",
                    portfolio.stale ? "border-warning/20 bg-warning/10 text-warning" : "border-success/20 bg-success/10 text-success",
                  )}
                  title={portfolio.asOf ? `Snapshot from ${new Date(portfolio.asOf).toLocaleString()}` : "Snapshot time unavailable"}
                >
                  <Clock3 className="h-3 w-3" />
                  Snapshot {formatAge(portfolio.ageMinutes)}
                  {portfolio.stale && <span className="font-semibold">· stale</span>}
                </div>
              )}
            </div>
            {loading ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="surface p-5">
                    <div className="skeleton h-3 w-1/2" />
                    <div className="skeleton mt-5 h-7 w-2/3" />
                    <div className="skeleton mt-4 h-3 w-3/4" />
                  </div>
                ))}
              </div>
            ) : (
              <StatsGrid data={statsData} />
            )}
          </section>

          <section className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(340px,0.8fr)]" aria-label="Trading activity">
            <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
              <div className="flex items-center justify-between gap-3 border-b border-border/70 px-5 py-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-foreground">Open positions</h2>
                    {!loading && <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{positionsData.length}</span>}
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">Paper execution · marked to last snapshot</p>
                </div>
                <Badge variant="outline" className="text-[9px] uppercase tracking-wider">All-in-one</Badge>
              </div>
              {loading ? (
                <div className="space-y-3 p-5">
                  {Array.from({ length: 4 }).map((_, index) => <div key={index} className="skeleton h-9 w-full" />)}
                </div>
              ) : (
                <PositionsTable
                  positions={positionsData}
                  currencySymbol={currencySymbol(currency)}
                  unavailable={!loading && portfolioError}
                />
              )}
            </Card>

            <Card id="alerts" className="min-w-0 scroll-mt-24 overflow-hidden border-border/70 bg-card/80">
              {loading ? (
                <div className="space-y-3 p-5">
                  <div className="skeleton h-4 w-1/3" />
                  {Array.from({ length: 3 }).map((_, index) => (
                    <div key={index} className="rounded-xl border border-border/60 p-4">
                      <div className="skeleton h-3 w-1/4" />
                      <div className="skeleton mt-3 h-4 w-3/4" />
                      <div className="skeleton mt-2 h-3 w-full" />
                    </div>
                  ))}
                </div>
              ) : (
                <AlertsPanel
                  alerts={alertsData}
                  unavailable={!loading && alertsError}
                  onAcknowledge={(alertId) => onAcknowledge?.(alertId)}
                />
              )}
            </Card>
          </section>

          <section className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
            <Card className="border-border/70 bg-card/80">
              <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
                <div>
                  <p className="section-eyebrow">Navigate</p>
                  <h2 className="mt-1 text-sm font-semibold text-foreground">Workspace shortcuts</h2>
                </div>
                <LayoutDashboard className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="grid gap-2 p-3 sm:grid-cols-3">
                {quickActions.map((action) => (
                  <Link
                    key={action.label}
                    to={action.href}
                    className="group relative rounded-xl border border-border/60 bg-background/30 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/25 hover:bg-background/60"
                  >
                    <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg ring-1 ring-inset", action.iconClass)}>
                      <action.icon className="h-4 w-4" />
                    </div>
                    <div className="mt-4 flex items-center justify-between gap-2">
                      <h3 className="text-xs font-semibold text-foreground">{action.label}</h3>
                      <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
                    </div>
                    <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">{action.description}</p>
                  </Link>
                ))}
              </div>
            </Card>

            <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
              <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-foreground">Live sessions</h2>
                    {!loading && <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{sessions.length}</span>}
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">Agent fleet activity</p>
                </div>
                <Link to="/sessions" className="inline-flex items-center gap-1 text-[10px] font-medium text-primary hover:underline">
                  View all
                  <ArrowUpRight className="h-3 w-3" />
                </Link>
              </div>
              {loading ? (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 5 }).map((_, index) => <div key={index} className="skeleton h-11 w-full" />)}
                </div>
              ) : sessionsError ? (
                <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center">
                  <Bot className="mb-3 h-6 w-6 text-warning/70" />
                  <p className="text-xs font-medium text-foreground">Sessions unavailable</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">The session hive could not be reached.</p>
                </div>
              ) : sessions.length === 0 ? (
                <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center">
                  <Bot className="mb-3 h-6 w-6 text-muted-foreground/60" />
                  <p className="text-xs font-medium text-foreground">No active sessions</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">The fleet has not published any active sessions.</p>
                </div>
              ) : (
                <ul className="divide-y divide-border/60">
                  {sessions.slice(0, 5).map((session) => (
                    <li key={`${session.provider}-${session.id}`}>
                      <Link
                        to={`/sessions/${session.provider}/${session.id}`}
                        className="group flex items-center gap-3 px-5 py-3 transition-colors hover:bg-primary/[0.035]"
                      >
                        <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", stateDot[session.state] ?? stateDot.unknown)} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-foreground group-hover:text-primary">{session.title || `${session.provider} · ${session.id}`}</p>
                          <p className="mt-0.5 truncate text-[10px] capitalize text-muted-foreground">{session.provider}</p>
                        </div>
                        <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[9px] font-medium capitalize", stateBadge[session.state] ?? stateBadge.unknown)}>
                          {session.state}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <section className="mt-8" aria-labelledby="system-health">
            <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="section-eyebrow">Infrastructure</p>
                <h2 id="system-health" className="mt-1 text-base font-semibold tracking-tight text-foreground">System health</h2>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { label: "Services", href: "/health" },
                  { label: "Launchd jobs", href: "/health/launchd" },
                  { label: "Resources", href: "/health/resources" },
                ].map((link) => (
                  <Link
                    key={link.href}
                    to={link.href}
                    className="inline-flex items-center gap-1 rounded-lg border border-border/65 bg-muted/25 px-2.5 py-1.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-primary/20 hover:text-primary"
                  >
                    {link.label}
                    <ArrowUpRight className="h-3 w-3" />
                  </Link>
                ))}
              </div>
            </div>
            <ServiceStatusGrid />
          </section>
    </>
  )
}

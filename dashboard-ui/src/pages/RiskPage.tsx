import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Eye, LockKeyhole, RefreshCw, ShieldCheck, TrendingDown, TriangleAlert, Wallet } from 'lucide-react'
import { AlertsPanel } from '@/components/Dashboard/AlertsPanel'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { riskApi, settingsApi } from '@/lib/api'
import { alertId, alertTitle, describeAlert } from '@/lib/alerts'
import { formatAge, formatDateTime, formatMoney, formatPercent } from '@/lib/format'
import { refetchKeys } from '@/lib/query-client'
import type { RiskAlert } from '@/types'

interface RiskPageProps {
  acknowledgedAlertIds: string[]
  onAcknowledge: (alertId: string) => void
}

export default function RiskPage({ acknowledgedAlertIds, onAcknowledge }: RiskPageProps) {
  const riskQuery = useQuery({
    queryKey: refetchKeys.risk,
    queryFn: riskApi.current,
    refetchInterval: 60_000,
  })
  const settingsQuery = useQuery({
    queryKey: refetchKeys.settings,
    queryFn: settingsApi.current,
    refetchInterval: 60_000,
  })

  const risk = riskQuery.data
  const settings = settingsQuery.data
  const portfolio = risk?.portfolio
  const currency = portfolio?.currency ?? 'INR'
  const panelAlerts = (risk?.alerts ?? []).map((alert: RiskAlert, index) => {
    const id = alertId(alert, index)
    return {
      alert_id: id,
      timestamp: alert.sourceAnalyzedAt ?? alert.detectedAt,
      severity: alert.severity,
      category: 'fundamentals',
      title: alertTitle(alert),
      message: describeAlert(alert),
      symbol: alert.symbol,
      acknowledged: acknowledgedAlertIds.includes(id),
    }
  })

  const refresh = () => {
    void riskQuery.refetch()
    void settingsQuery.refetch()
  }

  return (
    <>
      <PageHeader
        eyebrow="Capital protection"
        title="Risk Overview"
        description="Portfolio exposure, drawdown, published alerts, and enforced paper-trading guardrails."
        actions={
          <>
            <Badge variant={risk?.paperOnly ? 'success' : 'warning'} className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
              <ShieldCheck className="h-3.5 w-3.5" />
              {risk?.paperOnly ? 'Paper only' : 'Paper mode unverified'}
            </Badge>
            <Button type="button" variant="outline" className="h-11" onClick={refresh} disabled={riskQuery.isFetching || settingsQuery.isFetching}>
              <RefreshCw className={`mr-2 h-4 w-4 ${riskQuery.isFetching || settingsQuery.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {riskQuery.isPending || settingsQuery.isPending ? <PageLoading /> : riskQuery.isError || settingsQuery.isError || !risk || !portfolio?.available ? (
        <PageError
          title="Risk overview unavailable"
          description="The risk snapshot or safety settings could not be loaded. No risk status has been assumed."
          onRetry={refresh}
        />
      ) : (
        <>
          {portfolio.stale && (
            <div role="status" className="mt-6 flex items-start gap-3 rounded-xl border border-warning/25 bg-warning/10 px-4 py-3 text-sm text-warning">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Risk inputs are stale</p>
                <p className="mt-0.5 text-xs text-warning/80">Portfolio snapshot last observed {formatAge(portfolio.ageMinutes)}. Checked {formatDateTime(risk.checkedAt)}.</p>
              </div>
            </div>
          )}

          <section className="mt-7" aria-label="Risk summary">
            <StatsGrid data={[
              {
                title: 'Account Equity',
                value: formatMoney(portfolio.equity, currency),
                description: portfolio.broker === 'paper' ? 'paper account' : 'account equity',
                icon: <Wallet className="h-4 w-4" />,
              },
              {
                title: 'Max Drawdown',
                value: formatMoney(portfolio.maxDrawdown, currency),
                changeType: 'negative',
                description: 'from peak equity',
                icon: <TrendingDown className="h-4 w-4" />,
              },
              {
                title: 'Drawdown',
                value: formatPercent(portfolio.drawdownPercent),
                description: 'current vs peak equity',
                icon: <Activity className="h-4 w-4" />,
              },
              {
                title: 'Published Alerts',
                value: String(risk.alerts.length),
                changeType: risk.alerts.length > 0 ? 'negative' : 'positive',
                description: 'active conditions and transitions',
                icon: <TriangleAlert className="h-4 w-4" />,
              },
            ]} />
          </section>

          <section className="mt-5 grid gap-3 sm:grid-cols-3" aria-label="Safety guardrails">
            <GuardrailCard icon={<LockKeyhole className="h-5 w-5" />} title="Kill switch locked" positive={settings?.killSwitch === 'locked'} description="The dashboard cannot disable or bypass the trading kill switch." />
            <GuardrailCard icon={<Eye className="h-5 w-5" />} title="Read-only dashboard" positive={risk.readOnly && settings?.readOnly} description={`Allowed operations: ${settings?.allowedOperations.join(', ') ?? 'read'}. No mutation controls are exposed.`} />
            <GuardrailCard icon={<ShieldCheck className="h-5 w-5" />} title="Paper-only execution" positive={risk.paperOnly} description={risk.paperOnly ? 'The portfolio broker is verified as paper.' : 'Paper mode could not be verified.'} />
          </section>

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <Card className="min-w-0 border-border/70 bg-card/80">
              <div className="border-b border-border/70 px-5 py-4">
                <h2 className="text-sm font-semibold text-foreground">Exposure snapshot</h2>
                <p className="mt-1 text-[11px] text-muted-foreground">Capital allocation from the latest portfolio record</p>
              </div>
              <dl className="divide-y divide-border/60 px-5">
                <RiskMetric label="Cash" value={formatMoney(portfolio.cash, currency)} />
                <RiskMetric label="Market value" value={formatMoney(portfolio.marketValue, currency)} />
                <RiskMetric label="Unrealized P&L" value={formatMoney(portfolio.unrealizedPnl, currency, true)} />
                <RiskMetric label="Realized P&L" value={formatMoney(portfolio.realizedPnl, currency, true)} />
                <RiskMetric label="Open positions" value={String(portfolio.positions.length)} />
              </dl>
              <div className="border-t border-border/70 px-5 py-3 text-[11px] leading-5 text-muted-foreground">
                {portfolio.stale ? `Stale snapshot · ${formatAge(portfolio.ageMinutes)}` : 'Fresh portfolio snapshot'} · {portfolio.source.startsWith('sqlite:') ? 'SQLite state' : 'JSON fallback'}
              </div>
            </Card>

            <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
              <AlertsPanel alerts={panelAlerts} onAcknowledge={onAcknowledge} />
            </Card>
          </div>
        </>
      )}
    </>
  )
}

function GuardrailCard({ icon, title, description, positive = true }: { icon: ReactNode; title: string; description: string; positive?: boolean }) {
  return (
    <Card className={`flex gap-3 p-4 ${positive ? 'border-success/20 bg-success/[0.045]' : 'border-warning/25 bg-warning/[0.06]'}`}>
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset ${positive ? 'bg-success/10 text-success ring-success/15' : 'bg-warning/10 text-warning ring-warning/20'}`}>{icon}</div>
      <div>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{description}</p>
      </div>
    </Card>
  )
}

function RiskMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="numeric text-right font-mono text-xs font-medium text-foreground">{value}</dd>
    </div>
  )
}

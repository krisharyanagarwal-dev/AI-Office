import { useQuery } from '@tanstack/react-query'
import { Bell, BellRing, RefreshCw, ShieldAlert } from 'lucide-react'
import { AlertsPanel } from '@/components/Dashboard/AlertsPanel'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { fleetApi } from '@/lib/api'
import { alertId, alertTitle, describeAlert } from '@/lib/alerts'
import { formatDateTime } from '@/lib/format'
import { refetchKeys } from '@/lib/query-client'
import type { RiskAlert } from '@/types'

interface AlertsPageProps {
  acknowledgedAlertIds: string[]
  onAcknowledge: (alertId: string) => void
}

export default function AlertsPage({ acknowledgedAlertIds, onAcknowledge }: AlertsPageProps) {
  const alertsQuery = useQuery({
    queryKey: refetchKeys.alerts,
    queryFn: fleetApi.alerts,
    refetchInterval: 60_000,
  })

  const alerts = alertsQuery.data ?? []
  const panelAlerts = alerts.map((alert: RiskAlert, index) => {
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
  const unread = panelAlerts.filter((alert) => !alert.acknowledged).length
  const highSeverity = alerts.filter((alert) => alert.severity === 'high').length
  const lastAnalyzedAt = alerts.reduce<string | null>((latest, alert) => {
    const observed = alert.sourceAnalyzedAt ?? alert.detectedAt
    return !latest || new Date(observed) > new Date(latest) ? observed : latest
  }, null)

  const [isLive, setIsLive] = useState(true)
  useEffect(() => {
    setIsLive(alertsQuery.isSuccess && alertsQuery.data?.length > 0)
  }, [alertsQuery.isSuccess, alertsQuery.data])

  return (
    <>
      <PageHeader
        eyebrow="Risk monitoring"
        title="Risk Alerts"
        description="Fundamentals conditions and state transitions published by the live monitoring pipeline."
        actions={
          <>
            <Badge variant="outline" className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
              <BellRing className="h-3.5 w-3.5 text-primary" />
              {unread} unread
            </Badge>
            <Badge
              className={cn(
                'bg-primary/10 text-primary',
                !isLive && 'bg-destructive/10 text-destructive',
                !isLive && 'animate-pulse'
              )}
            >
              {isLive ? 'LIVE DATA' : 'MOCK FIXTURES'}
            </Badge>
            <Button type="button" variant="outline" className="h-11" onClick={() => void alertsQuery.refetch()} disabled={alertsQuery.isFetching}>
              <RefreshCw className={`mr-2 h-4 w-4 ${alertsQuery.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {alertsQuery.isPending ? <PageLoading /> : alertsQuery.isError ? (
        <PageError
          title="Risk alerts unavailable"
          description="The published fundamentals alert feed could not be reached. No alerts have been fabricated or hidden."
          onRetry={() => void alertsQuery.refetch()}
        />
      ) : (
        <>
          <section className="mt-7" aria-label="Alert summary">
            <StatsGrid data={[
              {
                title: 'Published Alerts',
                value: String(alerts.length),
                description: 'current conditions and transitions',
                icon: <Bell className="h-4 w-4" />,
              },
              {
                title: 'Unread',
                value: String(unread),
                changeType: unread > 0 ? 'negative' : 'positive',
                description: 'not acknowledged in this session',
                icon: <BellRing className="h-4 w-4" />,
              },
              {
                title: 'High Severity',
                value: String(highSeverity),
                changeType: highSeverity > 0 ? 'negative' : 'positive',
                description: 'requires review',
                icon: <ShieldAlert className="h-4 w-4" />,
              },
              {
                title: 'Last Analysis',
                value: lastAnalyzedAt ? formatDateTime(lastAnalyzedAt).split(', ').slice(-1)[0] : 'Unavailable',
                description: lastAnalyzedAt ? formatDateTime(lastAnalyzedAt).split(', ').slice(0, 2).join(', ') : 'no source timestamp',
                icon: <RefreshCw className="h-4 w-4" />,
              },
            ]} />
          </section>

          <Card className="mt-5 min-w-0 overflow-hidden border-border/70 bg-card/80">
            <AlertsPanel alerts={panelAlerts} onAcknowledge={onAcknowledge} isLive={isLive} />
          </Card>
          <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
            Acknowledgements are local to this browser session. The monitoring API remains read-only.
          </p>
        </>
      )}
    </>
  )
}
import { useQuery } from '@tanstack/react-query'
import { Eye, Laptop, LockKeyhole, Moon, RefreshCw, Settings2, ShieldCheck, Sun } from 'lucide-react'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { settingsApi } from '@/lib/api'
import { refetchKeys } from '@/lib/query-client'
import { cn } from '@/lib/utils'

interface SettingsPageProps {
  isDarkMode: boolean
  onToggleTheme: (dark: boolean) => void
}

const sourceLabels: Record<string, string> = {
  sessions: 'Session hive',
  fleet: 'Fleet agents',
  terminals: 'Observed terminals',
  portfolioDatabase: 'Portfolio database',
  portfolioFallback: 'Portfolio fallback',
  fundamentals: 'Fundamentals reports',
  alerts: 'Alert metrics',
}

export default function SettingsPage({ isDarkMode, onToggleTheme }: SettingsPageProps) {
  const settingsQuery = useQuery({
    queryKey: refetchKeys.settings,
    queryFn: settingsApi.current,
    refetchInterval: 60_000,
  })
  const settings = settingsQuery.data

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Read-only safety configuration, live data sources, and local appearance preferences."
        actions={
          <>
            <Badge variant="success" className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
              <LockKeyhole className="h-3.5 w-3.5" />
              Read-only mode
            </Badge>
            <Button type="button" variant="outline" className="h-11" onClick={() => void settingsQuery.refetch()} disabled={settingsQuery.isFetching}>
              <RefreshCw className={`mr-2 h-4 w-4 ${settingsQuery.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {settingsQuery.isPending ? <PageLoading /> : settingsQuery.isError || !settings ? (
        <PageError
          title="Settings unavailable"
          description="The API safety configuration could not be loaded. No settings have been assumed or changed."
          onRetry={() => void settingsQuery.refetch()}
        />
      ) : (
        <>
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-success/25 bg-success/[0.06] px-4 py-4">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-success" />
            <div>
              <p className="text-sm font-semibold text-foreground">Trading runtime controls are not exposed</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">This dashboard reads operational data only. It cannot place orders, change the kill switch, or mutate portfolio state.</p>
            </div>
          </div>

          <section className="mt-7" aria-label="Safety settings">
            <StatsGrid data={[
              {
                title: 'Access Mode',
                value: settings.readOnly ? 'Read-only' : 'Unknown',
                description: 'API mutation methods rejected',
                icon: <Eye className="h-4 w-4" />,
              },
              {
                title: 'Execution',
                value: settings.paperOnly ? 'Paper only' : 'Unknown',
                description: 'no live order routing',
                icon: <ShieldCheck className="h-4 w-4" />,
              },
              {
                title: 'Kill Switch',
                value: settings.killSwitch === 'locked' ? 'Locked' : 'Unknown',
                description: 'cannot be changed here',
                icon: <LockKeyhole className="h-4 w-4" />,
              },
              {
                title: 'Allowed Operations',
                value: settings.allowedOperations.join(', '),
                description: 'enforced by the unified API',
                icon: <Settings2 className="h-4 w-4" />,
              },
            ]} />
          </section>

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
            <div className="space-y-4">
              <Card className="border-border/70 bg-card/80">
                <div className="border-b border-border/70 px-5 py-4">
                  <h2 className="text-sm font-semibold text-foreground">Appearance</h2>
                  <p className="mt-1 text-[11px] text-muted-foreground">Stored locally in this browser</p>
                </div>
                <div className="grid grid-cols-2 gap-2 p-4">
                  <Button type="button" variant={isDarkMode ? 'default' : 'outline'} className="h-11" onClick={() => onToggleTheme(true)} aria-pressed={isDarkMode}>
                    <Moon className="mr-2 h-4 w-4" />
                    Dark
                  </Button>
                  <Button type="button" variant={!isDarkMode ? 'default' : 'outline'} className="h-11" onClick={() => onToggleTheme(false)} aria-pressed={!isDarkMode}>
                    <Sun className="mr-2 h-4 w-4" />
                    Light
                  </Button>
                </div>
              </Card>

              <Card className="border-border/70 bg-card/80">
                <div className="border-b border-border/70 px-5 py-4">
                  <h2 className="text-sm font-semibold text-foreground">API connection</h2>
                  <p className="mt-1 text-[11px] text-muted-foreground">Loopback-only unified service</p>
                </div>
                <dl className="space-y-3 px-5 py-4 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted-foreground">Host</dt>
                    <dd className="font-mono text-foreground">{settings.api.host}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted-foreground">Port</dt>
                    <dd className="font-mono text-foreground">{settings.api.port}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-muted-foreground">Transport</dt>
                    <dd className="font-medium text-foreground">HTTP + WebSocket</dd>
                  </div>
                </dl>
              </Card>
            </div>

            <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
              <div className="border-b border-border/70 px-5 py-4">
                <div className="flex items-center gap-2">
                  <Laptop className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold text-foreground">Live data sources</h2>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">Paths reported by the running API</p>
              </div>
              <dl className="divide-y divide-border/60">
                {Object.entries(settings.sources).map(([key, value]) => (
                  <div key={key} className="grid gap-1.5 px-5 py-3.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
                    <dt className="text-xs font-medium text-muted-foreground">{sourceLabels[key] ?? key}</dt>
                    <dd className={cn('break-all font-mono text-[11px] leading-5 text-foreground', key === 'portfolioFallback' && 'text-warning')}>{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="border-t border-border/70 px-5 py-3 text-[11px] leading-5 text-muted-foreground">
                SQLite is authoritative for portfolio and performance. The JSON portfolio path is used only when SQLite is unavailable.
              </div>
            </Card>
          </div>
        </>
      )}
    </>
  )
}

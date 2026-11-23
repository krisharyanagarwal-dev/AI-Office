import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { performanceApi, portfolioApi } from '@/lib/api'
import { formatDateTime, formatMoney, formatNumber } from '@/lib/format'
import { refetchKeys } from '@/lib/query-client'

export default function PerformancePage() {
  const performanceQuery = useQuery({
    queryKey: refetchKeys.performance,
    queryFn: performanceApi.current,
    refetchInterval: 60_000,
  })
  const portfolioQuery = useQuery({
    queryKey: refetchKeys.portfolio,
    queryFn: portfolioApi.current,
    refetchInterval: 60_000,
  })

  const performance = performanceQuery.data
  const currency = portfolioQuery.data?.currency
  const formatEquity = (value: number | null) => currency ? formatMoney(value, currency) : formatNumber(value)
  const successfulRuns = performance?.runs.filter((run) => run.status === 'success').length ?? 0

  return (
    <>
      <PageHeader
        eyebrow="Execution history"
        title="Performance"
        description="Recorded all-in-one runs, account equity, and order outcomes from the SQLite state history."
        actions={
          <>
            <Badge variant="outline" className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
              <Activity className="h-3.5 w-3.5 text-primary" />
              {performance?.runs.length ?? 0} recorded runs
            </Badge>
            <Button type="button" variant="outline" className="h-11" onClick={() => void performanceQuery.refetch()} disabled={performanceQuery.isFetching}>
              <RefreshCw className={`mr-2 h-4 w-4 ${performanceQuery.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {performanceQuery.isPending ? <PageLoading /> : performanceQuery.isError || !performance?.available ? (
        <PageError
          title="Performance unavailable"
          description="The SQLite run history could not be loaded. No performance results have been estimated or substituted."
          onRetry={() => void performanceQuery.refetch()}
        />
      ) : (
        <>
          <section className="mt-7" aria-label="Performance summary">
            <StatsGrid data={[
              {
                title: 'Latest Equity',
                value: formatEquity(performance.latestEquity),
                description: currency ? 'account currency' : 'account units',
                icon: <Activity className="h-4 w-4" />,
              },
              {
                title: 'Best Equity',
                value: formatEquity(performance.bestEquity),
                description: 'recorded run high',
                icon: <TrendingUp className="h-4 w-4" />,
              },
              {
                title: 'Worst Equity',
                value: formatEquity(performance.worstEquity),
                description: 'recorded run low',
                icon: <TrendingDown className="h-4 w-4" />,
              },
              {
                title: 'Successful Runs',
                value: `${successfulRuns} / ${performance.runs.length}`,
                changeType: successfulRuns === performance.runs.length ? 'positive' : 'negative',
                description: 'completed without run errors',
                icon: <CheckCircle2 className="h-4 w-4" />,
              },
            ]} />
          </section>

          <Card className="mt-5 min-w-0 overflow-hidden border-border/70 bg-card/80">
            <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Run history</h2>
                <p className="mt-1 text-[11px] text-muted-foreground">Newest recorded run first</p>
              </div>
              <Badge variant="outline" className="w-fit text-[9px] uppercase tracking-wider">SQLite state</Badge>
            </div>
            {performance.runs.length === 0 ? (
              <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
                <Activity className="mb-3 h-7 w-7 text-muted-foreground/60" />
                <p className="text-sm font-medium text-foreground">No performance runs available</p>
                <p className="mt-1 text-xs text-muted-foreground">The state database has not published any all-in-one runs.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table className="min-w-[920px]" aria-label="Recorded performance runs">
                  <TableHeader className="bg-muted/25">
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Run</TableHead>
                      <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Started</TableHead>
                      <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Status</TableHead>
                      <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Mode</TableHead>
                      <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">Equity</TableHead>
                      <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">Total P&L</TableHead>
                      <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">Filled</TableHead>
                      <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">Rejected</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {performance.runs.map((run) => (
                      <TableRow key={run.runId} className="border-border/60 hover:bg-primary/[0.035]">
                        <TableCell className="px-4 py-4">
                          <p className="font-mono text-xs font-medium text-foreground">{run.runId}</p>
                          {run.errors.length > 0 && (
                            <ul className="mt-2 max-w-xs space-y-1 text-[10px] text-destructive">
                              {run.errors.map((error, index) => <li key={`${error}-${index}`}>{error}</li>)}
                            </ul>
                          )}
                        </TableCell>
                        <TableCell className="px-4 py-4 text-xs text-muted-foreground">{formatDateTime(run.startedAt)}</TableCell>
                        <TableCell className="px-4 py-4">
                          <Badge variant={run.status === 'success' ? 'success' : 'destructive'} className="text-[10px] capitalize">{run.status}</Badge>
                        </TableCell>
                        <TableCell className="px-4 py-4 text-xs text-muted-foreground">
                          {run.paperOnly ? 'Paper' : 'Mode unavailable'}{run.dryRun ? ' · dry run' : ''}
                        </TableCell>
                        <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-foreground">{formatEquity(run.equity)}</TableCell>
                        <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-muted-foreground">{currency ? formatMoney(run.totalPnl, currency, true) : formatNumber(run.totalPnl)}</TableCell>
                        <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-foreground">{run.filledOrders}</TableCell>
                        <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-muted-foreground">{run.rejectedOrders}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            <div className="border-t border-border/70 px-5 py-3 text-[11px] text-muted-foreground">
              History source: <span className="break-all font-mono">{performance.source}</span>
            </div>
          </Card>
        </>
      )}
    </>
  )
}

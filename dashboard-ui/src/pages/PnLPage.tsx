import { useQuery } from '@tanstack/react-query'
import { DollarSign, Inbox, RefreshCw, TrendingUp, Wallet } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { performanceApi, portfolioApi } from '@/lib/api'
import { formatAge, formatDateTime, formatMoney, formatPercent } from '@/lib/format'
import { refetchKeys } from '@/lib/query-client'
import type { PortfolioPosition } from '@/types'

interface PnLAggregation {
  label: string
  positions: number
  quantity: number
  side: 'LONG' | 'SHORT' | 'FLAT'
  unrealized: number
  realized: number
  total: number
  notional: number
}

function aggregateBy<T extends PortfolioPosition>(
  positions: T[],
  keyOf: (position: T) => string,
): PnLAggregation[] {
  const grouped = new Map<string, PnLAggregation>()
  for (const position of positions) {
    const key = keyOf(position)
    const signedQty = position.side === 'LONG' ? position.quantity : -position.quantity
    let current = grouped.get(key)
    if (!current) {
      current = {
        label: key,
        positions: 1,
        quantity: Math.abs(signedQty),
        side: signedQty > 0 ? 'LONG' : signedQty < 0 ? 'SHORT' : 'FLAT',
        unrealized: position.unrealizedPnl,
        realized: position.realizedPnl,
        total: position.unrealizedPnl + position.realizedPnl,
        notional: position.notional,
      }
      grouped.set(key, current)
      continue
    }
    const carried = current.side === 'LONG' ? current.quantity : current.side === 'SHORT' ? -current.quantity : 0
    const netQty = carried + signedQty
    current.positions += 1
    current.quantity = Math.abs(netQty)
    current.side = netQty > 0 ? 'LONG' : netQty < 0 ? 'SHORT' : 'FLAT'
    current.unrealized += position.unrealizedPnl
    current.realized += position.realizedPnl
    current.total = current.unrealized + current.realized
    current.notional += position.notional
  }
  return Array.from(grouped.values()).sort((a, b) => b.total - a.total)
}

interface PnLTableProps {
  title: string
  description: string
  kind: 'symbol' | 'strategy'
  rows: PnLAggregation[]
  emptyMessage: string
  currency: string
  stale: boolean
  ageMinutes: number | null
}

function PnLTable({
  title,
  description,
  kind,
  rows,
  emptyMessage,
  currency,
  stale,
  ageMinutes,
}: PnLTableProps) {
  const columns =
    kind === 'symbol'
      ? [
          { key: 'label', label: 'Symbol' },
          { key: 'positions', label: 'Positions' },
          { key: 'side', label: 'Side' },
          { key: 'quantity', label: 'Quantity' },
          { key: 'unrealized', label: 'Unrealized' },
          { key: 'realized', label: 'Realized' },
          { key: 'total', label: 'Total P&L' },
          { key: 'notional', label: 'Notional' },
        ]
      : [
          { key: 'label', label: 'Strategy' },
          { key: 'positions', label: 'Positions' },
          { key: 'unrealized', label: 'Unrealized' },
          { key: 'realized', label: 'Realized' },
          { key: 'total', label: 'Total P&L' },
          { key: 'return', label: 'Return %' },
        ]

  const money = (value: number, showSign = false, key?: string) => (
    <TableCell
      key={key}
      className={cn(
        'numeric px-4 py-3.5 text-right font-mono text-xs',
        value >= 0 ? 'text-success' : 'text-destructive',
      )}
    >
      {formatMoney(value, currency, showSign)}
    </TableCell>
  )

  return (
    <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
      <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <p className="mt-1 text-[11px] text-muted-foreground">{description}</p>
        </div>
        <Badge variant="outline" className="w-fit text-[9px] uppercase tracking-wider">
          Paper · all-in-one
        </Badge>
      </div>
      {rows.length === 0 ? (
        <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
          <Inbox className="mb-3 h-7 w-7 opacity-50" />
          <p className="text-sm font-medium text-foreground">{emptyMessage}</p>
          <p className="mt-1 text-xs text-muted-foreground">Roll up open positions from the latest snapshot.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table className="min-w-[880px]" aria-label={title}>
            <TableHeader className="bg-muted/25">
              <TableRow className="hover:bg-transparent">
                {columns.map((column) => (
                  <TableHead
                    key={column.key}
                    className="px-4 text-[10px] font-semibold uppercase tracking-[0.12em]"
                  >
                    {column.label}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.label} className="border-border/60 hover:bg-primary/[0.035]">
                  {columns.map((column) => {
                    switch (column.key) {
                      case 'label':
                        return (
                          <TableCell key="label" className="px-4 py-3.5">
                            <span className="text-[13px] font-semibold tracking-wide text-foreground">
                              {row.label}
                            </span>
                          </TableCell>
                        )
                      case 'side':
                        return (
                          <TableCell key="side" className="px-4 py-3.5 text-right">
                            <Badge
                              variant={
                                row.side === 'LONG'
                                  ? 'success'
                                  : row.side === 'SHORT'
                                  ? 'destructive'
                                  : 'outline'
                              }
                              className="text-[10px]"
                            >
                              {row.side}
                            </Badge>
                          </TableCell>
                        )
                      case 'quantity':
                        return (
                          <TableCell
                            key="quantity"
                            className="numeric px-4 py-3.5 text-right font-mono text-xs text-foreground"
                          >
                            {row.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                          </TableCell>
                        )
                      case 'positions':
                        return (
                          <TableCell
                            key="positions"
                            className="numeric px-4 py-3.5 text-right font-mono text-xs text-foreground"
                          >
                            {row.positions}
                          </TableCell>
                        )
                      case 'unrealized':
                        return money(row.unrealized, true, 'unrealized')
                      case 'realized':
                        return money(row.realized, true, 'realized')
                      case 'total':
                        return money(row.total, true, 'total')
                      case 'notional':
                        return money(row.notional, false, 'notional')
                      case 'return':
                        return (
                          <TableCell key="return" className="numeric px-4 py-3.5 text-right font-mono text-xs text-muted-foreground">
                            {row.notional > 0
                              ? formatPercent((row.total / row.notional) * 100, true)
                              : 'Unavailable'}
                          </TableCell>
                        )
                    }
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <div className="border-t border-border/70 px-5 py-3 text-[11px] leading-5 text-muted-foreground">
        {stale ? `Stale snapshot · ${formatAge(ageMinutes)}` : 'Fresh portfolio snapshot'} · Paper ·
        all-in-one
      </div>
    </Card>
  )
}

export default function PnLPage() {
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
  const portfolio = portfolioQuery.data
  const currency = portfolio?.currency ?? 'INR'
  const positions = portfolio?.positions ?? []
  const strategyLabel = `${portfolio?.broker ?? 'paper'} · all-in-one`
  const enriched = positions.map((position) => ({ ...position, strategy: strategyLabel }))
  const bySymbol = aggregateBy(positions, (position) => position.symbol)
  const byStrategy = aggregateBy(enriched, (position) => position.strategy)

  const totalPnl = portfolio?.totalPnl ?? null
  const equity = portfolio?.equity ?? null
  const totalReturn =
    totalPnl !== null && equity !== null && equity > 0 ? (totalPnl / equity) * 100 : null

  const isLoading = performanceQuery.isPending || portfolioQuery.isPending
  const isUnavailable = portfolioQuery.isError || !portfolio?.available

  const refresh = () => {
    void performanceQuery.refetch()
    void portfolioQuery.refetch()
  }

  return (
    <>
      <PageHeader
        eyebrow="Profit & loss"
        title="P&L Dashboard"
        description="Realized and unrealized P&L from the paper portfolio snapshot, rolled up by symbol and strategy. Read-only view — no execution paths are exposed."
        actions={
          <>
            <Badge variant="outline" className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
              <Wallet className="h-3.5 w-3.5 text-primary" />
              {portfolio?.broker ?? 'paper'} · read-only
            </Badge>
            <Button type="button" variant="outline" className="h-11" onClick={refresh} disabled={isLoading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {isLoading ? (
        <PageLoading />
      ) : isUnavailable ? (
        <PageError
          title="P&L data unavailable"
          description="The portfolio snapshot could not be loaded. No P&L figures have been assumed or substituted."
          onRetry={refresh}
        />
      ) : (
        <>
          {portfolio.stale && (
            <div role="status" className="mt-6 flex items-start gap-3 rounded-xl border border-warning/25 bg-warning/10 px-4 py-3 text-sm text-warning">
              <Wallet className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Portfolio snapshot is stale</p>
                <p className="mt-0.5 text-xs text-warning/80">
                  Last observed {formatAge(portfolio.ageMinutes)}. P&L figures are not current market quotes.
                </p>
              </div>
            </div>
          )}

          <section className="mt-7" aria-label="P&L summary">
            <StatsGrid data={[
              {
                title: 'Total P&L',
                value: formatMoney(totalPnl, currency, true),
                change: totalPnl !== null ? formatMoney(portfolio.unrealizedPnl, currency, true) : undefined,
                changeType: totalPnl === null ? 'neutral' : totalPnl < 0 ? 'negative' : 'positive',
                description: 'unrealized + realized',
                icon: <DollarSign className="h-4 w-4" />,
              },
              {
                title: 'Unrealized',
                value: formatMoney(portfolio.unrealizedPnl, currency, true),
                changeType:
                  portfolio.unrealizedPnl === null ? 'neutral' : portfolio.unrealizedPnl < 0 ? 'negative' : 'positive',
                description: 'marked to snapshot',
                icon: <TrendingUp className="h-4 w-4" />,
              },
              {
                title: 'Realized',
                value: formatMoney(portfolio.realizedPnl, currency, true),
                changeType:
                  portfolio.realizedPnl === null ? 'neutral' : portfolio.realizedPnl < 0 ? 'negative' : 'positive',
                description: 'closed positions',
                icon: <DollarSign className="h-4 w-4" />,
              },
              {
                title: 'Total return',
                value: formatPercent(totalReturn, true),
                changeType: totalReturn === null ? 'neutral' : totalReturn < 0 ? 'negative' : 'positive',
                description: 'total P&L vs current equity',
                icon: <Wallet className="h-4 w-4" />,
              },
            ]} />
          </section>

          <section className="mt-5 grid gap-4 xl:grid-cols-2" aria-label="P&L breakdown">
            <PnLTable
              title="By symbol"
              description="Unrealized and realized P&L rolled up across open positions for each symbol."
              kind="symbol"
              rows={bySymbol}
              emptyMessage="No open positions"
              currency={currency}
              stale={portfolio.stale}
              ageMinutes={portfolio.ageMinutes}
            />
            <PnLTable
              title="By strategy"
              description="P&L rolled up by execution strategy. Positions are tagged with the portfolio broker strategy."
              kind="strategy"
              rows={byStrategy}
              emptyMessage="No strategy data"
              currency={currency}
              stale={portfolio.stale}
              ageMinutes={portfolio.ageMinutes}
            />
          </section>

          {performance?.available && performance.runs.length > 0 ? (
            <section className="mt-5" aria-label="Run-level P&L history">
              <Card className="min-w-0 overflow-hidden border-border/70 bg-card/80">
                <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="text-sm font-semibold text-foreground">Run history</h2>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Recorded all-in-one run outcomes from the SQLite state history.
                    </p>
                  </div>
                  <Badge variant="outline" className="w-fit text-[9px] uppercase tracking-wider">
                    SQLite state
                  </Badge>
                </div>
                <div className="overflow-x-auto">
                  <Table className="min-w-[880px]" aria-label="Recorded performance runs">
                    <TableHeader className="bg-muted/25">
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Run</TableHead>
                        <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Started</TableHead>
                        <TableHead className="px-4 text-[10px] uppercase tracking-[0.12em]">Status</TableHead>
                        <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">
                          Equity
                        </TableHead>
                        <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">
                          Total P&L
                        </TableHead>
                        <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">Filled</TableHead>
                        <TableHead className="px-4 text-right text-[10px] uppercase tracking-[0.12em]">
                          Rejected
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {performance.runs.map((run) => (
                        <TableRow key={run.runId} className="border-border/60 hover:bg-primary/[0.035]">
                          <TableCell className="px-4 py-4">
                            <p className="font-mono text-xs font-medium text-foreground">{run.runId}</p>
                          </TableCell>
                          <TableCell className="px-4 py-4 text-xs text-muted-foreground">
                            {formatDateTime(run.startedAt)}
                          </TableCell>
                          <TableCell className="px-4 py-4">
                            <Badge
                              variant={run.status === 'success' ? 'success' : 'destructive'}
                              className="text-[10px] capitalize"
                            >
                              {run.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-foreground">
                            {formatMoney(run.equity ?? null, currency)}
                          </TableCell>
                          <TableCell
                            className={cn(
                              'numeric px-4 py-4 text-right font-mono text-xs',
                              (run.totalPnl ?? 0) >= 0 ? 'text-success' : 'text-destructive',
                            )}
                          >
                            {formatMoney(run.totalPnl ?? null, currency, true)}
                          </TableCell>
                          <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-foreground">
                            {run.filledOrders}
                          </TableCell>
                          <TableCell className="numeric px-4 py-4 text-right font-mono text-xs text-muted-foreground">
                            {run.rejectedOrders}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <div className="border-t border-border/70 px-5 py-3 text-[11px] text-muted-foreground">
                  History source: <span className="break-all font-mono">{performance.source}</span>
                </div>
              </Card>
            </section>
          ) : null}
        </>
      )}
    </>
  )
}

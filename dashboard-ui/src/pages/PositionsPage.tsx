import { useQuery } from '@tanstack/react-query'
import { CircleDollarSign, RefreshCw, Wallet, WalletCards } from 'lucide-react'
import { PositionsTable } from '@/components/Dashboard/PositionsTable'
import { StatsGrid } from '@/components/Dashboard/StatsCards'
import { PageError, PageHeader, PageLoading } from '@/components/PageState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { portfolioApi } from '@/lib/api'
import { currencySymbol, formatAge, formatMoney } from '@/lib/format'
import { refetchKeys } from '@/lib/query-client'

export default function PositionsPage() {
  const portfolioQuery = useQuery({
    queryKey: refetchKeys.portfolio,
    queryFn: portfolioApi.current,
    refetchInterval: 60_000,
  })

  const portfolio = portfolioQuery.data
  const currency = portfolio?.currency ?? 'INR'

  return (
    <>
      <PageHeader
        eyebrow="Capital"
        title="Positions"
        description="Open paper positions, live marks, and unrealized P&L from the authoritative portfolio snapshot."
        actions={
          <>
            {portfolio && (
              <Badge variant="outline" className="h-9 gap-2 px-3 text-[10px] uppercase tracking-[0.12em]">
                <WalletCards className="h-3.5 w-3.5 text-primary" />
                {portfolio.broker ?? 'Portfolio'} trading
              </Badge>
            )}
            <Button type="button" variant="outline" className="h-11" onClick={() => void portfolioQuery.refetch()} disabled={portfolioQuery.isFetching}>
              <RefreshCw className={`mr-2 h-4 w-4 ${portfolioQuery.isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </>
        }
      />

      {portfolioQuery.isPending ? <PageLoading /> : portfolioQuery.isError || !portfolio?.available ? (
        <PageError
          title="Portfolio unavailable"
          description="The portfolio snapshot could not be loaded. No balances or positions have been substituted."
          onRetry={() => void portfolioQuery.refetch()}
        />
      ) : (
        <>
          {portfolio.stale && (
            <div role="status" className="mt-6 flex items-start gap-3 rounded-xl border border-warning/25 bg-warning/10 px-4 py-3 text-sm text-warning">
              <Wallet className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Portfolio snapshot is stale</p>
                <p className="mt-0.5 text-xs text-warning/80">Last observed {formatAge(portfolio.ageMinutes)}. Values are not current market quotes.</p>
              </div>
            </div>
          )}

          <section className="mt-7" aria-label="Portfolio summary">
            <StatsGrid data={[
              {
                title: 'Total Equity',
                value: formatMoney(portfolio.equity, currency),
                description: portfolio.broker === 'paper' ? 'paper account' : 'account equity',
                icon: <CircleDollarSign className="h-4 w-4" />,
              },
              {
                title: 'Market Value',
                value: formatMoney(portfolio.marketValue, currency),
                description: `${portfolio.positions.length} open position${portfolio.positions.length === 1 ? '' : 's'}`,
                icon: <WalletCards className="h-4 w-4" />,
              },
              {
                title: 'Unrealized P&L',
                value: formatMoney(portfolio.unrealizedPnl, currency, true),
                changeType: portfolio.unrealizedPnl !== null && portfolio.unrealizedPnl < 0 ? 'negative' : 'positive',
                description: 'marked to snapshot',
                icon: <RefreshCw className="h-4 w-4" />,
              },
              {
                title: 'Cash',
                value: formatMoney(portfolio.cash, currency),
                description: 'available balance',
                icon: <Wallet className="h-4 w-4" />,
              },
            ]} />
          </section>

          <Card className="mt-5 min-w-0 overflow-hidden border-border/70 bg-card/80">
            <div className="flex flex-col gap-3 border-b border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-foreground">Open positions</h2>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">{portfolio.positions.length}</span>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">Paper execution · marked to last snapshot</p>
              </div>
              <Badge variant="outline" className="w-fit text-[9px] uppercase tracking-wider">
                {portfolio.source.startsWith('sqlite:') ? 'SQLite state' : portfolio.source.startsWith('json:') ? 'JSON fallback' : portfolio.source}
              </Badge>
            </div>
            <PositionsTable
              positions={portfolio.positions.map((position) => ({
                symbol: position.symbol,
                side: position.side,
                quantity: position.quantity,
                entryPrice: position.avgEntryPrice,
                currentPrice: position.markPrice,
                unrealizedPnl: position.unrealizedPnl,
                unrealizedPnlPct: position.unrealizedPnlPct,
                realizedPnl: position.realizedPnl,
                strategy: `${portfolio.broker ?? 'paper'} · all-in-one`,
                timestamp: portfolio.asOf ?? undefined,
              }))}
              currencySymbol={currencySymbol(currency)}
            />
            <div className="border-t border-border/70 px-5 py-3 text-[11px] text-muted-foreground">
              Snapshot source: <span className="break-all font-mono">{portfolio.source}</span>
            </div>
          </Card>
        </>
      )}
    </>
  )
}

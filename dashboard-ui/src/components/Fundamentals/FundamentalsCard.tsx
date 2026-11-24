import { useParams } from 'react-router-dom'
import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { usePolling } from '@/lib/use-polling'
import type { Fundamentals } from '@/types'

interface FundamentalsCardProps {
  symbol?: string
  initialData?: Fundamentals[]
}

function formatRatio(value: number | null, digits = 2): string {
  if (value === null) return 'N/A'
  return value.toFixed(digits)
}

function formatPercent(value: number | null): string {
  if (value === null) return 'N/A'
  return `${(value * 100).toFixed(1)}%`
}

function formatYield(value: number | null): string {
  if (value === null) return 'N/A'
  return `${value.toFixed(2)}%`
}

function currencyFor(symbol: string): string {
  return symbol.endsWith('.NS') ? 'INR' : 'USD'
}

function formatMoney(value: number | null, symbol: string): string {
  if (value === null) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currencyFor(symbol),
    maximumFractionDigits: 0,
  }).format(value)
}

function formatPrice(value: number | null, symbol: string): string {
  if (value === null) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currencyFor(symbol),
    maximumFractionDigits: 2,
  }).format(value)
}

function FlagRow({ label, value }: { label: string; value: string | null }) {
  return (
    <p className="text-sm">
      {label}: <span className="font-medium">{value ?? 'N/A'}</span>
    </p>
  )
}

export function FundamentalsCard({ symbol: symbolProp, initialData }: FundamentalsCardProps = {}) {
  const { symbol: symbolParam } = useParams<{ symbol: string }>()
  const symbol = symbolProp ?? symbolParam
  const seeded = initialData?.find((row) => row.symbol === symbol)

  const {
    data: fetched,
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<Fundamentals | null>({
    fetch: (signal) =>
      fetch(`/api/fundamentals/${encodeURIComponent(symbol ?? '')}`, { signal }).then(async (response) => {
        if (response.status === 404) return null
        if (!response.ok) throw new Error(`Fundamentals request failed (${response.status})`)
        const fundamental = await response.json() as Fundamentals
        if (!fundamental?.symbol) throw new Error('Fundamentals response was invalid')
        return fundamental
      }),
    interval: 60_000,
    immediate: Boolean(symbol) && !seeded,
    maxFailureCount: 5,
  })

  const data = seeded ?? fetched ?? null
  const hasError = !seeded && error

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading fundamentals for {symbol}…</div>
  }

  if (hasError) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">Fundamentals unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The published fundamentals feed could not be reached.</p>
        <button
          type="button"
          onClick={retry}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </button>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-muted-foreground" />
        <p className="text-sm font-semibold text-foreground">Fundamentals not found</p>
        <p className="mt-1 text-xs text-muted-foreground">No published fundamentals are available for {symbol}.</p>
      </div>
    )
  }

  const coverage = data.scoreCoverage ?? 100

  return (
    <div className="p-6 rounded border bg-card shadow-sm max-w-3xl">
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-xl font-bold">{data.name} ({data.symbol})</h2>
        <span
          className="text-3xl font-bold"
          title={
            coverage < 100
              ? `Partial score: based on ${coverage}% of the model weight`
              : 'Based on the full model weight'
          }
        >
          {data.score}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Company Info</h3>
          <p className="text-sm">{data.sector}</p>
          {data.industry && <p className="text-sm text-muted-foreground">{data.industry}</p>}
          <p className="text-sm">Price: {formatPrice(data.price, data.symbol)}</p>
          <p className="text-sm text-muted-foreground">Updated: {data.updatedAt}</p>
        </div>

        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Valuation</h3>
          <div className="space-y-1">
            <p className="text-sm">P/E: {formatRatio(data.peRatio)}</p>
            <p className="text-sm">P/B: {formatRatio(data.pbRatio)}</p>
            <p className="text-sm">EV/EBITDA: {formatRatio(data.evEbitda)}</p>
            <p className="text-sm">Market Cap: {formatMoney(data.marketCap, data.symbol)}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 my-6">
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Financial Health</h3>
          <div className="space-y-1">
            <p className="text-sm">ROE: {formatPercent(data.roe)}</p>
            <p className="text-sm">Profit Margin: {formatPercent(data.profitMargin)}</p>
            <p className="text-sm">Current Ratio: {formatRatio(data.currentRatio)}</p>
            <p className="text-sm">Debt to Equity: {formatRatio(data.debtToEquity)}</p>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Growth & Income</h3>
          <div className="space-y-1">
            <p className="text-sm">Revenue Growth: {formatPercent(data.revenueGrowth)}</p>
            <p className="text-sm">Earnings Growth: {formatPercent(data.earningsGrowth)}</p>
            <p className="text-sm">Dividend Yield: {formatYield(data.dividendYield)}</p>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium text-muted-foreground mb-2">Producer Flags</h3>
        <div className="grid grid-cols-2 gap-1">
          <FlagRow label="Valuation" value={data.valuationFlag} />
          <FlagRow label="Leverage" value={data.leverageFlag} />
          <FlagRow label="Liquidity" value={data.liquidityFlag} />
          <FlagRow label="Momentum" value={data.momentumFlag} />
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-medium text-muted-foreground mb-2">Composite Score</h3>
        <p className="text-2xl font-bold">{data.score}</p>
        <p className="text-xs text-muted-foreground">
          out of 100 — valuation 30, profitability 22, balance sheet 23, growth 20, momentum 5
        </p>
        <p className={`mt-1 text-xs ${coverage < 100 ? 'text-warning' : 'text-muted-foreground'}`}>
          {coverage >= 100
            ? 'Full model coverage.'
            : `Partial score: based on ${coverage}% of the model weight; the missing groups have no data for this symbol.`}
        </p>
      </div>
    </div>
  )
}

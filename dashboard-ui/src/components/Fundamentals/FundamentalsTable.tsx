import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { usePolling } from '@/lib/use-polling'
import { formatAge } from '@/lib/format'
import type { Fundamentals } from '@/types'

interface FundamentalsTableProps {
  data?: Fundamentals[]
  onSelect?: (symbol: string) => void
}

export function FundamentalsTable({ data, onSelect }: FundamentalsTableProps = {}) {
  const [sortBy, setSortBy] = useState<keyof Fundamentals | ''>('score')
  const [sortDesc, setSortDesc] = useState(true)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const searchQuery = searchParams.get('search')?.trim() ?? ''

  const {
    data: fetchedRows = [],
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<Fundamentals[]>({
    fetch: (signal) =>
      fetch('/api/fundamentals', { signal }).then(async (response) => {
        if (!response.ok) throw new Error(`Fundamentals request failed (${response.status})`)
        const result = await response.json() as Fundamentals[]
        if (!Array.isArray(result)) throw new Error('Fundamentals response was invalid')
        return result
      }),
    interval: 60_000,
    immediate: !data,
    maxFailureCount: 5,
  })

  const rows = data ?? fetchedRows ?? []
  const hasError = !data && error

  const handleRowSelect = (symbol: string) => {
    if (onSelect) {
      onSelect(symbol)
      return
    }
    navigate(`/fundamentals/${symbol}`)
  }

  const handleSort = (column: keyof Fundamentals) => {
    if (sortBy === column) {
      setSortDesc((prev) => !prev)
      return
    }
    setSortBy(column)
    setSortDesc(false)
  }

  const matchingRows = rows.filter((row) => {
    if (!searchQuery) return true
    return [row.symbol, row.name, row.sector, row.industry]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(searchQuery.toLowerCase()))
  })

  const sortedData = [...matchingRows].sort((a, b) => {
    if (!sortBy) return 0

    const aVal = a[sortBy]
    const bVal = b[sortBy]

    if (aVal === null || aVal === undefined) return 1
    if (bVal === null || bVal === undefined) return -1

    const result =
      typeof aVal === 'number' && typeof bVal === 'number'
        ? aVal - bVal
        : String(aVal).localeCompare(String(bVal))

    return sortDesc ? -result : result
  })

  const sortIndicator = (column: keyof Fundamentals) =>
    sortBy === column ? (
      <span className={`ml-1 text-xs ${sortDesc ? 'text-muted-foreground' : 'opacity-100'}`}>
        {sortDesc ? '↓' : '↑'}
      </span>
    ) : null

  const sortableColumns: { key: keyof Fundamentals; label: string }[] = [
    { key: 'score', label: 'Score' },
    { key: 'peRatio', label: 'P/E Ratio' },
    { key: 'marketCap', label: 'Market Cap' },
    { key: 'revenueGrowth', label: 'Revenue Growth' },
    { key: 'sector', label: 'Sector' },
    { key: 'updatedAt', label: 'Updated' },
  ]

  const headerClass = 'p-3 text-left text-sm font-medium text-foreground cursor-pointer select-none'

  const formatMarketCap = (value: number | null, symbol: string): string => {
    if (value === null) return 'N/A'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: symbol.endsWith('.NS') ? 'INR' : 'USD',
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(value)
  }

  const formatUpdated = (updatedAt: string | null): string => {
    if (!updatedAt) return 'Unavailable'
    const minutes = Math.floor((Date.now() - new Date(updatedAt).getTime()) / 60_000)
    return formatAge(minutes)
  }

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading fundamentals…</div>
  }

  if (hasError && rows.length === 0) {
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

  return (
    <div className="space-y-3">
      {hasError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-warning/20 bg-warning/10 px-4 py-3 text-xs text-warning">
          <span>Showing the last known fundamentals data.</span>
          <button type="button" onClick={retry} className="inline-flex items-center gap-1.5 font-medium hover:underline">
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      )}
      {searchQuery && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-primary/20 bg-primary/[0.06] px-4 py-3 text-xs">
          <span className="text-muted-foreground">
            {matchingRows.length} result{matchingRows.length === 1 ? '' : 's'} for <span className="font-medium text-foreground">“{searchQuery}”</span>
          </span>
          <button type="button" onClick={() => navigate('/fundamentals')} className="min-h-11 font-medium text-primary hover:underline sm:min-h-0">
            Clear search
          </button>
        </div>
      )}
      <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] rounded border border-border bg-card">
        <thead>
          <tr className="border-b">
            {sortableColumns.map(({ key, label }) => (
              <th
                key={key}
                className={headerClass}
                role="button"
                tabIndex={0}
                aria-sort={sortBy === key ? (sortDesc ? 'descending' : 'ascending') : 'none'}
                onClick={() => handleSort(key)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    handleSort(key)
                  }
                }}
              >
                {label}
                {sortIndicator(key)}
              </th>
            ))}
            <th className="p-3 text-left text-sm font-medium text-foreground">Symbol</th>
          </tr>
        </thead>
        <tbody>
          {sortedData.length === 0 && (
            <tr>
              <td colSpan={7} className="p-6 text-center text-sm text-muted-foreground">
                {searchQuery ? 'No fundamentals match your search.' : 'No fundamentals available.'}
              </td>
            </tr>
          )}
          {sortedData.map((fundamental) => (
            <tr
              key={fundamental.symbol}
              role="button"
              tabIndex={0}
              aria-label={`View ${fundamental.symbol} details`}
              className="hover:bg-accent/20 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => handleRowSelect(fundamental.symbol)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  handleRowSelect(fundamental.symbol)
                }
              }}
            >
              <td
                className="p-3"
                title={
                  (fundamental.scoreCoverage ?? 100) < 100
                    ? `Partial score: based on ${fundamental.scoreCoverage}% of the model weight`
                    : 'Based on the full model weight'
                }
              >
                {fundamental.score}
              </td>
              <td className="p-3">{fundamental.peRatio ?? 'N/A'}</td>
              <td className="p-3">{formatMarketCap(fundamental.marketCap, fundamental.symbol)}</td>
              <td className="p-3">{fundamental.revenueGrowth ?? 'N/A'}</td>
              <td className="p-3">{fundamental.sector}</td>
              <td className="p-3 text-muted-foreground">{formatUpdated(fundamental.updatedAt)}</td>
              <td className="p-3 font-medium">{fundamental.symbol}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  )
}

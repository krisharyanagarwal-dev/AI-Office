import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { usePolling } from '@/lib/use-polling'
import type { Fundamentals } from '@/types'
import { FundamentalsTable } from './FundamentalsTable'

interface FundamentalsFilterProps {
  initialData?: Fundamentals[]
  onSectorChange?: (sector: string | null) => void
  onScoreRangeChange?: (min: number, max: number) => void
}

export function FundamentalsFilter({
  initialData,
  onSectorChange,
  onScoreRangeChange,
}: FundamentalsFilterProps = {}) {
  const [selectedSector, setSelectedSector] = useState('')
  const [scoreMin, setScoreMin] = useState(0)
  const [scoreMax, setScoreMax] = useState(100)

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
    immediate: !initialData,
    maxFailureCount: 5,
  })

  const rows = initialData ?? fetchedRows ?? []
  const hasError = !initialData && error
  const sectors = useMemo(
    () => [...new Set(rows.map((row) => row.sector).filter(Boolean))].sort(),
    [rows],
  )

  useEffect(() => {
    onSectorChange?.(selectedSector || null)
  }, [selectedSector, onSectorChange])

  useEffect(() => {
    onScoreRangeChange?.(scoreMin, scoreMax)
  }, [scoreMin, scoreMax, onScoreRangeChange])

  const filteredData = useMemo(
    () =>
      rows.filter((row) => {
        const sectorMatch = !selectedSector || row.sector === selectedSector
        const scoreMatch = row.score >= scoreMin && row.score <= scoreMax
        return sectorMatch && scoreMatch
      }),
    [rows, selectedSector, scoreMin, scoreMax]
  )

  const inputClass =
    'mt-1 block w-full rounded border border-input bg-background px-3 py-2 text-sm font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading filter options…</div>
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
    <div className="space-y-4">
      {hasError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-warning/20 bg-warning/10 px-4 py-3 text-xs text-warning">
          <span>Showing the last known fundamentals data.</span>
          <button type="button" onClick={retry} className="inline-flex items-center gap-1.5 font-medium hover:underline">
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-foreground mb-2" htmlFor="sector-filter">
          Sector
        </label>
        <select
          id="sector-filter"
          value={selectedSector}
          onChange={(e) => setSelectedSector(e.target.value)}
          className={inputClass}
        >
          <option value="">All Sectors</option>
          {sectors.map((sector) => (
            <option key={sector} value={sector}>
              {sector}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">Score Range</label>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <span className="text-xs text-muted-foreground">Min</span>
            <input
              type="number"
              value={scoreMin}
              onChange={(e) => setScoreMin(Number(e.target.value))}
              className={inputClass}
              min="0"
              max="100"
            />
          </div>
          <div>
            <span className="text-xs text-muted-foreground">Max</span>
            <input
              type="number"
              value={scoreMax}
              onChange={(e) => setScoreMax(Number(e.target.value))}
              className={inputClass}
              min="0"
              max="100"
            />
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {filteredData.length} of {rows.length} symbols match
        </p>
      </div>

      <FundamentalsTable data={filteredData} />
    </div>
  )
}

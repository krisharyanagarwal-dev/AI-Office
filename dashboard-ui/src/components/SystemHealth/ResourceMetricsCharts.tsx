import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePolling } from '@/lib/use-polling'

interface ResourceMetrics {
  cpuPercent: number
  memoryPercent: number
  diskPercent: number
  networkInMbps: number
  networkOutMbps: number
  timestamp: string
}

interface ResourceMetricsChartsProps {
  refreshInterval?: number
}

const usageClass = (percent: number) => percent > 80 ? 'bg-destructive' : percent > 60 ? 'bg-warning' : 'bg-success'

export function ResourceMetricsCharts({ refreshInterval = 10000 }: ResourceMetricsChartsProps) {
  const {
    data: metrics,
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<ResourceMetrics>({
    fetch: (signal) =>
      fetch('/api/health/resources', { signal }).then(async (response) => {
        if (!response.ok) throw new Error(`Resource request failed (${response.status})`)
        const result = await response.json() as ResourceMetrics
        if (typeof result.cpuPercent !== 'number' || typeof result.memoryPercent !== 'number' || typeof result.diskPercent !== 'number') {
          throw new Error('Resource response was invalid')
        }
        return result
      }),
    interval: refreshInterval,
    maxFailureCount: 5,
  })

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading resource metrics…</div>
  }

  if (error && !metrics) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">Resource metrics unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The resource endpoint could not be reached.</p>
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

  if (!metrics) return null

  const gauges = [
    { label: 'CPU Usage', percent: metrics.cpuPercent },
    { label: 'Memory Usage', percent: metrics.memoryPercent },
    { label: 'Disk Usage', percent: metrics.diskPercent },
  ]

  return (
    <div className="surface space-y-6 p-5 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight text-foreground">System Resource Metrics</h2>
        {error && <span role="alert" className="text-xs text-warning">Showing last known state</span>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {gauges.map((gauge) => (
          <div key={gauge.label} className="rounded-xl border border-border/60 bg-background/35 p-4">
            <h3 className="text-xs font-medium text-muted-foreground">{gauge.label}</h3>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="numeric text-xl font-semibold text-foreground">{gauge.percent.toFixed(1)}%</span>
              <span className="numeric text-[11px] text-muted-foreground">{(100 - gauge.percent).toFixed(1)}% free</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className={cn('h-full rounded-full transition-[width] duration-700', usageClass(gauge.percent))} style={{ width: `${Math.max(0, Math.min(100, gauge.percent))}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-border/60 bg-background/35 p-4">
          <h3 className="text-xs font-medium text-muted-foreground">Network</h3>
          <div className="numeric mt-3 flex gap-6 text-sm text-foreground">
            <span>In: {metrics.networkInMbps.toFixed(2)} Mbps</span>
            <span>Out: {metrics.networkOutMbps.toFixed(2)} Mbps</span>
          </div>
        </div>
        <div className="rounded-xl border border-border/60 bg-background/35 p-4">
          <h3 className="text-xs font-medium text-muted-foreground">Last updated</h3>
          <p className="numeric mt-3 text-sm text-foreground">{new Date(metrics.timestamp).toLocaleString()}</p>
        </div>
      </div>
    </div>
  )
}

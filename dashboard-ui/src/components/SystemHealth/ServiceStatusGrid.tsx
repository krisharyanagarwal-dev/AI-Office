import { Activity, AlertTriangle, RefreshCw, Server } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePolling } from '@/lib/use-polling'

interface ServiceStatus {
  name: string
  port: number
  path: string
  status: 'healthy' | 'degraded' | 'down'
  lastCheck: string
  responseTimeMs: number
}

interface ServiceStatusGridProps {
  refreshInterval?: number
}

const statusStyles: Record<ServiceStatus['status'], { badge: string; dot: string; bar: string; label: string }> = {
  healthy: {
    badge: 'border-success/20 bg-success/10 text-success',
    dot: 'bg-success',
    bar: 'bg-success',
    label: 'Operational',
  },
  degraded: {
    badge: 'border-warning/20 bg-warning/10 text-warning',
    dot: 'bg-warning',
    bar: 'bg-warning',
    label: 'Degraded',
  },
  down: {
    badge: 'border-destructive/20 bg-destructive/10 text-destructive',
    dot: 'bg-destructive',
    bar: 'bg-destructive',
    label: 'Offline',
  },
}

export function ServiceStatusGrid({ refreshInterval = 10000 }: ServiceStatusGridProps) {
  const {
    data,
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<ServiceStatus[]>({
    fetch: (signal) =>
      fetch('/api/health/services', { signal }).then(async (response) => {
        if (!response.ok) throw new Error(`Health request failed (${response.status})`)
        return (await response.json()) as ServiceStatus[]
      }),
    interval: refreshInterval,
    maxFailureCount: 5,
  })

  const services = data ?? []

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Loading system health">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="surface p-5">
            <div className="skeleton h-4 w-2/3" />
            <div className="skeleton mt-3 h-3 w-1/2" />
            <div className="skeleton mt-5 h-1.5 w-full" />
          </div>
        ))}
      </div>
    )
  }

  if (error && services.length === 0) {
    return (
      <div className="surface flex flex-col items-center justify-center px-6 py-12 text-center">
        <AlertTriangle className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">System health is unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The health endpoint could not be reached.</p>
        <button
          type="button"
          onClick={retry}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {error && services.length > 0 && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-warning/20 bg-warning/10 px-4 py-3 text-xs text-warning">
          <span>Showing the last known service health.</span>
          <button type="button" onClick={retry} className="inline-flex items-center gap-1.5 font-medium hover:underline">
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {services.map((service) => {
        const style = statusStyles[service.status]
        return (
          <article key={service.name} className="surface group p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/20">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-muted/35 text-muted-foreground transition-colors group-hover:border-primary/20 group-hover:text-primary">
                  <Server className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <h3 className="truncate text-[13px] font-semibold text-foreground">{service.name}</h3>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">127.0.0.1:{service.port}</p>
                </div>
              </div>
              <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] font-semibold', style.badge)}>
                <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
                {style.label}
              </span>
            </div>
            <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn('h-full rounded-full transition-[width] duration-700', style.bar)}
                style={{ width: `${Math.max(4, Math.min(100, (service.responseTimeMs / 1000) * 100))}%` }}
              />
            </div>
            <div className="mt-2.5 flex items-center justify-between text-[10px] text-muted-foreground">
              <span className="numeric inline-flex items-center gap-1">
                <Activity className="h-3 w-3" />
                {service.responseTimeMs}ms
              </span>
              <time dateTime={service.lastCheck}>
                {new Date(service.lastCheck).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </time>
            </div>
          </article>
        )
      })}
      </div>
    </div>
  )
}

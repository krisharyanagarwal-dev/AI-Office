import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePolling } from '@/lib/use-polling'

interface LaunchdJob {
  label: string
  status: 'running' | 'stopped' | 'error'
  pid: number | null
  lastExitCode: number | null
  startInterval: number | null
}

interface LaunchdJobsTableProps {
  refreshInterval?: number
}

const statusClass: Record<LaunchdJob['status'], string> = {
  running: 'border-success/20 bg-success/10 text-success',
  stopped: 'border-border bg-muted/60 text-muted-foreground',
  error: 'border-destructive/20 bg-destructive/10 text-destructive',
}

export function LaunchdJobsTable({ refreshInterval = 10000 }: LaunchdJobsTableProps) {
  const {
    data,
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<LaunchdJob[]>({
    fetch: (signal) =>
      fetch('/api/health/launchd', { signal }).then(async (response) => {
        if (!response.ok) throw new Error(`Launchd request failed (${response.status})`)
        const result = await response.json() as LaunchdJob[]
        if (!Array.isArray(result)) throw new Error('Launchd response was invalid')
        return result
      }),
    interval: refreshInterval,
    maxFailureCount: 5,
  })

  const jobs = data ?? []

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading launchd jobs…</div>
  }

  if (error && jobs.length === 0) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">Launchd jobs unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The launchd endpoint could not be reached.</p>
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
      {error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-warning/20 bg-warning/10 px-4 py-3 text-xs text-warning">
          <span>Showing the last known launchd state.</span>
          <button type="button" onClick={retry} className="font-medium underline">Retry</button>
        </div>
      )}
      <div className="surface overflow-x-auto">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="border-b border-border/70">
              {['Label', 'Status', 'PID', 'Exit Code', 'Start Interval'].map((label) => (
                <th key={label} className="p-3 text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="p-8 text-center text-sm text-muted-foreground">No launchd jobs reported.</td>
              </tr>
            )}
            {jobs.map((job) => (
              <tr key={job.label} className="border-b border-border/50 last:border-0 hover:bg-primary/[0.035]">
                <td className="p-3 text-xs font-medium text-foreground">{job.label}</td>
                <td className="p-3">
                  <span className={cn('rounded-full border px-2 py-1 text-[10px] font-medium capitalize', statusClass[job.status])}>{job.status}</span>
                </td>
                <td className="numeric p-3 text-xs text-muted-foreground">{job.pid ?? 'N/A'}</td>
                <td className="numeric p-3 text-xs text-muted-foreground">{job.lastExitCode ?? 'N/A'}</td>
                <td className="numeric p-3 text-xs text-muted-foreground">{job.startInterval ?? 'N/A'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

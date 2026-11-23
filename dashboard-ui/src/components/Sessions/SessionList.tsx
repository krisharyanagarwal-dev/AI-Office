import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatSeconds } from '@/lib/format'
import type { Session } from '@/types'

interface SessionListProps {
  onSelect?: (session: Session) => void
}

const stateClass: Record<string, string> = {
  idle: 'border-border bg-muted/60 text-muted-foreground',
  busy: 'border-info/20 bg-info/10 text-info',
  blocked: 'border-destructive/20 bg-destructive/10 text-destructive',
  unknown: 'border-warning/20 bg-warning/10 text-warning',
}

export function SessionList({ onSelect }: SessionListProps = {}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false

    async function fetchSessions() {
      try {
        const response = await fetch('/api/sessions')
        if (!response.ok) throw new Error(`Sessions request failed (${response.status})`)
        const data = await response.json() as Session[]
        if (!Array.isArray(data)) throw new Error('Sessions response was invalid')
        if (!cancelled) {
          setSessions(data)
          setError(false)
        }
      } catch (fetchError) {
        console.error('Failed to fetch sessions:', fetchError)
        if (!cancelled) setError(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchSessions()
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading sessions…</div>
  }

  if (error && sessions.length === 0) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">Sessions unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The session hive could not be reached.</p>
        <button
          type="button"
          onClick={() => {
            setLoading(true)
            setReloadKey((value) => value + 1)
          }}
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
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="section-eyebrow">Agent fleet</p>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-[-0.04em] text-foreground">Live sessions</h1>
          <p className="mt-2 text-sm text-muted-foreground">Inspect current work, state, and blockers.</p>
        </div>
        <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">{sessions.length} sessions</span>
      </div>
      {error && <p role="alert" className="rounded-xl border border-warning/20 bg-warning/10 p-3 text-xs text-warning">Showing the last known session state.</p>}
      {sessions.length === 0 ? (
        <div className="surface flex flex-col items-center px-6 py-16 text-center">
          <Bot className="mb-3 h-7 w-7 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">No active sessions</p>
          <p className="mt-1 text-xs text-muted-foreground">The fleet has not published any sessions.</p>
        </div>
      ) : (
        <ul className="surface divide-y divide-border/60 overflow-hidden" aria-label="Sessions">
          {sessions.map((session) => (
            <li key={`${session.provider}-${session.id}`}>
              <button
                type="button"
                onClick={() => {
                  onSelect?.(session)
                  navigate(`/sessions/${session.provider}/${session.id}`)
                }}
                className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-primary/[0.035]"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{session.title}</span>
                  <span className="mt-1 block truncate text-[11px] capitalize text-muted-foreground">{session.provider} · {session.source} · heartbeat {formatSeconds(session.heartbeatAgeSeconds)}</span>
                  {session.blocker && <span className="mt-1 block text-xs text-destructive">{session.blocker}</span>}
                  {session.stale && <span className="mt-1 block text-[11px] font-medium text-warning">Stale heartbeat · last observed {session.observedAt ? new Date(session.observedAt).toLocaleString() : 'Unavailable'}</span>}
                </span>
                <span className={cn('shrink-0 rounded-full border px-2 py-1 text-[10px] font-medium capitalize', stateClass[session.state] ?? stateClass.unknown)}>{session.state}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

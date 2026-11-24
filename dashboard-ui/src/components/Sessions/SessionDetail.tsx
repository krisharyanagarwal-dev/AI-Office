import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Bot, RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatSeconds } from '@/lib/format'
import { usePolling } from '@/lib/use-polling'
import type { Message, Session } from '@/types'

const stateClass: Record<string, string> = {
  idle: 'border-border bg-muted/60 text-muted-foreground',
  busy: 'border-info/20 bg-info/10 text-info',
  blocked: 'border-destructive/20 bg-destructive/10 text-destructive',
  unknown: 'border-warning/20 bg-warning/10 text-warning',
}

export function SessionDetail() {
  const { provider, id } = useParams<{ provider: string; id: string }>()
  const navigate = useNavigate()
  const providerSegment = encodeURIComponent(provider ?? '')
  const idSegment = encodeURIComponent(id ?? '')

  const {
    data,
    isLoading: loading,
    isError: error,
    retry,
  } = usePolling<{
    session: Session | null
    messages: Message[]
    messagesError: boolean
  }>({
    fetch: (signal) =>
      (async () => {
        let session: Session | null = null
        let messages: Message[] = []
        let messagesFailed = false

        try {
          const sessionResponse = await fetch(`/api/sessions/${providerSegment}/${idSegment}`, { signal })
          if (sessionResponse.status === 404) {
            session = null
          } else {
            if (!sessionResponse.ok) throw new Error(`Session request failed (${sessionResponse.status})`)
            const responseData = await sessionResponse.json() as Session
            if (!responseData?.id) throw new Error('Session response was invalid')
            session = responseData
          }
        } catch (caught) {
          console.error('Failed to fetch session:', caught)
          throw caught
        }

        if (session) {
          try {
            const messagesResponse = await fetch(`/api/sessions/${providerSegment}/${idSegment}/messages`, { signal })
            if (!messagesResponse.ok) throw new Error(`Transcript request failed (${messagesResponse.status})`)
            const responseMessages = await messagesResponse.json() as Message[]
            if (!Array.isArray(responseMessages)) throw new Error('Transcript response was invalid')
            messages = responseMessages
          } catch (caught) {
            console.error('Failed to fetch messages:', caught)
            messagesFailed = true
          }
        }

        return { session, messages, messagesError: messagesFailed }
      })(),
    interval: 60_000,
    maxFailureCount: 5,
  })

  const session = data?.session ?? null
  const messages = data?.messages ?? []
  const messagesError = data?.messagesError ?? false

  if (loading) {
    return <div className="surface p-8 text-sm text-muted-foreground">Loading session detail…</div>
  }

  if (error) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <TriangleExclamationPoint className="mb-3 h-7 w-7 text-warning" />
        <p className="text-sm font-semibold text-foreground">Session unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">The session hive could not be reached.</p>
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

  if (!session) {
    return (
      <div className="surface flex flex-col items-center px-6 py-12 text-center">
        <Bot className="mb-3 h-7 w-7 text-muted-foreground" />
        <p className="text-sm font-semibold text-foreground">Session not found</p>
        <p className="mt-1 text-xs text-muted-foreground">The requested session is not published in the live hive.</p>
        <button
          type="button"
          onClick={() => navigate('/sessions')}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs font-medium text-foreground hover:bg-muted"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to sessions
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <button
        type="button"
        onClick={() => navigate('/sessions')}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to sessions
      </button>

      <section className="surface p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="section-eyebrow">Agent fleet</p>
            <h1 className="mt-2 break-words font-display text-3xl font-semibold tracking-[-0.04em] text-foreground">{session.title}</h1>
            <p className="mt-2 text-xs text-muted-foreground">Live session detail from the configured adapter.</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <span className={cn('inline-flex w-fit items-center rounded-full border px-2.5 py-1 text-[10px] font-medium capitalize', stateClass[session.state] ?? stateClass.unknown)}>
              {session.state}
            </span>
            {session.stale && (
              <span className="inline-flex w-fit items-center rounded-full border border-warning/20 bg-warning/10 px-2.5 py-1 text-[10px] font-medium text-warning">
                Stale heartbeat
              </span>
            )}
          </div>
        </div>

        <dl className="mt-6 grid gap-4 border-t border-border/70 pt-5 text-xs sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">Provider</dt>
            <dd className="mt-1 font-medium capitalize text-foreground">{session.provider}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Session ID</dt>
            <dd className="mt-1 break-all font-mono text-[11px] text-foreground">{session.id}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Observed</dt>
            <dd className="mt-1 font-medium text-foreground">{session.observedAt ? new Date(session.observedAt).toLocaleString() : 'Unavailable'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Process</dt>
            <dd className="mt-1 font-medium text-foreground">{session.processAlive === true ? `Alive${session.processId ? ` · PID ${session.processId}` : ''}` : session.processAlive === false ? 'Not running' : 'Unavailable'}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Heartbeat</dt>
            <dd className="mt-1 font-medium text-foreground">{formatSeconds(session.heartbeatAgeSeconds)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Source</dt>
            <dd className="mt-1 font-medium capitalize text-foreground">{session.source || 'Unavailable'}</dd>
          </div>
        </dl>

        {session.blocker && (
          <div role="alert" className="mt-5 rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-xs text-destructive">
            <span className="font-semibold">Blocker:</span> {session.blocker}
          </div>
        )}
      </section>

      <section className="surface overflow-hidden" aria-labelledby="session-transcript">
        <div className="border-b border-border/70 px-5 py-4">
          <p className="section-eyebrow">Adapter output</p>
          <h2 id="session-transcript" className="mt-1 text-base font-semibold text-foreground">Transcript</h2>
        </div>
        <div className="p-5">
          {messagesError ? (
            <div role="alert" className="flex items-start gap-3 rounded-xl border border-warning/20 bg-warning/10 p-4 text-sm text-warning">
              <TriangleExclamationPoint className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-medium">Transcript unavailable from the configured session adapter.</p>
                <p className="mt-1 text-xs text-warning/80">No transcript has been fabricated or substituted.</p>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center py-10 text-center">
              <Bot className="mb-3 h-7 w-7 text-muted-foreground" />
              <p className="text-sm font-medium text-foreground">No messages published</p>
              <p className="mt-1 text-xs text-muted-foreground">The adapter returned an empty transcript.</p>
            </div>
          ) : (
            <div className="max-h-[32rem] space-y-3 overflow-y-auto">
              {messages.map((message) => (
                <article key={message.id} className={cn('rounded-xl border p-4 text-sm', message.role === 'user' ? 'border-info/20 bg-info/10 text-foreground' : 'border-border/70 bg-muted/30 text-foreground')}>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{message.role}</p>
                  <p className="whitespace-pre-wrap break-words leading-6">{message.text}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

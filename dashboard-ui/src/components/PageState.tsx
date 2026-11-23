import type { ReactNode } from 'react'
import { RefreshCw, TriangleExclamationPoint } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <section className="animate-rise-in flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p className="section-eyebrow">{eyebrow}</p>
        <h1 className="mt-3 font-display text-[32px] font-semibold leading-[1.05] tracking-[-0.045em] text-foreground sm:text-[38px]">
          {title}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </section>
  )
}

export function PageLoading({ cards = 3 }: { cards?: number }) {
  return (
    <div className="mt-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Loading live data" aria-busy="true">
      {Array.from({ length: cards }, (_, index) => (
        <div key={index} className="surface p-5">
          <div className="skeleton h-3 w-1/2" />
          <div className="skeleton mt-5 h-7 w-2/3" />
          <div className="skeleton mt-4 h-3 w-3/4" />
        </div>
      ))}
    </div>
  )
}

export function PageError({
  title,
  description,
  onRetry,
}: {
  title: string
  description: string
  onRetry: () => void
}) {
  return (
    <div role="alert" className="surface mt-7 flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-warning/20 bg-warning/10 text-warning">
        <TriangleExclamationPoint className="h-5 w-5" />
      </div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
      <Button type="button" variant="outline" className="mt-5 h-11" onClick={onRetry}>
        <RefreshCw className="mr-2 h-4 w-4" />
        Retry
      </Button>
    </div>
  )
}

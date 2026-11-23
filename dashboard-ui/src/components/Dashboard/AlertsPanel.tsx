"use client"

import * as React from "react"
import { ArrowDown, ArrowUp, BellOff, Check, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface AlertsPanelProps {
  alerts: Array<{
    alert_id: string
    timestamp: string
    severity: "critical" | "high" | "medium" | "low"
    category: string
    title: string
    message: string
    symbol?: string
    acknowledged: boolean
    acknowledged_at?: string
  }>
  onAcknowledge?: (alertId: string) => void
  unavailable?: boolean
}

const severityClass: Record<AlertsPanelProps["alerts"][number]["severity"], string> = {
  critical: "border-destructive/30 bg-destructive/10 text-destructive",
  high: "border-orange-400/25 bg-orange-400/10 text-orange-300",
  medium: "border-warning/25 bg-warning/10 text-warning",
  low: "border-info/25 bg-info/10 text-info",
}

export function AlertsPanel({ alerts, onAcknowledge, unavailable = false }: AlertsPanelProps) {
  const [filter, setFilter] = React.useState<"all" | "unacknowledged">("all")
  const [sortOrder, setSortOrder] = React.useState<"asc" | "desc">("desc")

  const filteredAlerts = alerts
    .filter((alert) => filter === "all" || (filter === "unacknowledged" && !alert.acknowledged))
    .sort((a, b) => sortOrder === "desc"
      ? new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      : new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )

  return (
    <div className="flex h-full min-h-[420px] flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">Risk alerts</h3>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
            {alerts.filter((alert) => !alert.acknowledged).length} unread
          </span>
        </div>
        <div className="flex items-center gap-1">
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value as "all" | "unacknowledged")}
            className="h-11 rounded-md border border-border/70 bg-background/60 px-2 text-[11px] text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            aria-label="Filter alerts"
          >
            <option value="all">All</option>
            <option value="unacknowledged">Unread</option>
          </select>
          <button
            type="button"
            onClick={() => setSortOrder((value) => value === "asc" ? "desc" : "asc")}
            className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={`Sort ${sortOrder === "asc" ? "newest" : "oldest"} first`}
          >
            {sortOrder === "asc" ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {filteredAlerts.length === 0 ? (
          <div className="flex h-full min-h-72 flex-col items-center justify-center px-6 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-muted/40 text-muted-foreground">
              <BellOff className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium text-foreground">{unavailable ? "Risk alerts unavailable" : "No active alerts"}</p>
            <p className="mt-1 max-w-52 text-xs leading-5 text-muted-foreground">
              {unavailable ? "The published fundamentals feed could not be reached." : "Published fundamentals are clear for the monitored rules."}
            </p>
          </div>
        ) : (
          filteredAlerts.map((alert) => (
            <article
              key={alert.alert_id}
              className={cn(
                "relative overflow-hidden rounded-xl border border-border/65 bg-background/35 p-4 transition-colors hover:bg-background/60",
                alert.acknowledged && "opacity-60",
              )}
            >
              <span className={cn("absolute inset-y-3 left-0 w-0.5 rounded-full", severityClass[alert.severity].split(" ")[2])} />
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className={cn("rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider", severityClass[alert.severity])}>
                      {alert.severity}
                    </span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
                      {alert.category}
                    </span>
                    {alert.symbol && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold text-primary">
                        {alert.symbol}
                      </span>
                    )}
                  </div>
                  <h4 className="mt-2 text-[13px] font-semibold leading-5 text-foreground">{alert.title}</h4>
                  <p className="mt-1 line-clamp-3 text-[11px] leading-[18px] text-muted-foreground">{alert.message}</p>
                  <time className="mt-2 block text-[10px] text-muted-foreground/80" dateTime={alert.timestamp}>
                    {new Date(alert.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </time>
                </div>
                {alert.acknowledged ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-success/10 px-2 py-1 text-[10px] font-medium text-success">
                    <Check className="h-3 w-3" />
                    Seen
                  </span>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-11 shrink-0 rounded-md px-3 text-[11px]"
                    onClick={() => onAcknowledge?.(alert.alert_id)}
                  >
                    Acknowledge
                  </Button>
                )}
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  )
}

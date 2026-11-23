"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface StatCardProps {
  title: string
  value: string
  change?: string
  changeType?: "positive" | "negative" | "neutral"
  icon: React.ReactNode
  description?: string
}

export function StatCard({ title, value, change, changeType = "neutral", icon, description }: StatCardProps) {
  const toneClass =
    changeType === "positive"
      ? "bg-success"
      : changeType === "negative"
      ? "bg-destructive"
      : "bg-primary"

  return (
    <Card className="group relative overflow-hidden border-border/70 bg-card/80 p-0 transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card">
      <div className={cn("absolute inset-x-0 top-0 h-px opacity-70", toneClass)} />
      <div className="pointer-events-none absolute -right-10 -top-12 h-28 w-28 rounded-full bg-primary/[0.035] blur-2xl opacity-70 transition-opacity group-hover:opacity-100" />
      <CardHeader className="flex flex-row items-center justify-between space-y-0 p-5 pb-0">
        <CardTitle className="text-[12px] font-medium tracking-wide text-muted-foreground">{title}</CardTitle>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-muted/45 text-muted-foreground transition-colors group-hover:border-primary/20 group-hover:bg-primary/10 group-hover:text-primary">
          {icon}
        </div>
      </CardHeader>
      <CardContent className="p-5 pt-4">
        <div className="numeric font-display text-[27px] font-semibold leading-none tracking-[-0.035em] text-foreground">{value}</div>
        <div className="mt-3 flex min-h-4 flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
          {change && (
            <span
              className={cn(
                "numeric font-medium",
                changeType === "positive" && "text-success",
                changeType === "negative" && "text-destructive",
                changeType === "neutral" && "text-foreground",
              )}
            >
              {change}
            </span>
          )}
          {description && <span className="text-muted-foreground">{description}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

export function StatsGrid({ data }: { data: Array<{
  title: string
  value: string
  change?: string
  changeType?: "positive" | "negative" | "neutral"
  icon: React.ReactNode
  description?: string
}> }) {
  return (
    <div className={cn(
      'grid gap-3',
      data.length === 1 && 'grid-cols-1',
      data.length === 2 && 'sm:grid-cols-2',
      data.length === 3 && 'sm:grid-cols-2 xl:grid-cols-3',
      data.length >= 4 && 'sm:grid-cols-2 xl:grid-cols-4',
    )}>
      {data.map((item, index) => (
        <div key={item.title} className="animate-rise-in" style={{ animationDelay: `${index * 55}ms` }}>
          <StatCard {...item} />
        </div>
      ))}
    </div>
  )
}

"use client"

import { Inbox } from "lucide-react"
import { cn } from "@/lib/utils"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

interface PositionsTableProps {
  positions: Array<{
    symbol: string
    side: "LONG" | "SHORT"
    quantity: number
    entryPrice: number
    currentPrice: number
    unrealizedPnl: number
    unrealizedPnlPct: number
    realizedPnl: number
    strategy: string
    timestamp?: string
  }>
  currencySymbol?: string
  unavailable?: boolean
}

const columns = [
  { field: "symbol", label: "Symbol" },
  { field: "side", label: "Side" },
  { field: "quantity", label: "Quantity" },
  { field: "entryPrice", label: "Entry" },
  { field: "currentPrice", label: "Mark" },
  { field: "unrealizedPnl", label: "Unrealized" },
  { field: "unrealizedPnlPct", label: "Return" },
  { field: "realizedPnl", label: "Realized" },
  { field: "strategy", label: "Execution" },
]

export function PositionsTable({ positions, currencySymbol = "$", unavailable = false }: PositionsTableProps) {
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[880px]" aria-label="Open trading positions">
        <TableHeader className="bg-muted/25">
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => (
              <TableHead
                key={column.field}
                className={cn("h-10 px-4 text-[10px] font-semibold uppercase tracking-[0.12em]", column.field !== "symbol" && column.field !== "strategy" && "text-right")}
              >
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="h-48 text-center">
                <div className="flex flex-col items-center justify-center text-muted-foreground">
                  <Inbox className="mb-3 h-7 w-7 opacity-50" />
                  <p className="text-sm font-medium text-foreground">{unavailable ? "Portfolio unavailable" : "No open positions"}</p>
                  <p className="mt-1 text-xs">{unavailable ? "The portfolio snapshot could not be loaded." : "The paper portfolio is currently flat."}</p>
                </div>
              </TableCell>
            </TableRow>
          ) : (
            positions.map((position) => (
              <TableRow key={`${position.symbol}-${position.side}-${position.strategy}-${position.timestamp ?? 'undated'}`} className="border-border/60 hover:bg-primary/[0.035]">
                <TableCell className="px-4 py-3.5">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-[10px] font-bold text-primary">
                      {position.symbol.slice(0, 2)}
                    </span>
                    <span className="text-[13px] font-semibold tracking-wide text-foreground">{position.symbol}</span>
                  </div>
                </TableCell>
                <TableCell className="px-4 py-3.5 text-right">
                  <Badge variant={position.side === "LONG" ? "success" : "destructive"} className="text-[10px]">
                    {position.side}
                  </Badge>
                </TableCell>
                <TableCell className="numeric px-4 py-3.5 text-right font-mono text-xs text-foreground">{position.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })}</TableCell>
                <TableCell className="numeric px-4 py-3.5 text-right font-mono text-xs text-muted-foreground">{currencySymbol}{position.entryPrice.toFixed(2)}</TableCell>
                <TableCell className="numeric px-4 py-3.5 text-right font-mono text-xs text-foreground">{currencySymbol}{position.currentPrice.toFixed(2)}</TableCell>
                <TableCell className={cn("numeric px-4 py-3.5 text-right font-mono text-xs font-medium", position.unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                  {position.unrealizedPnl >= 0 ? "+" : "−"}{currencySymbol}{Math.abs(position.unrealizedPnl).toFixed(2)}
                </TableCell>
                <TableCell className={cn("numeric px-4 py-3.5 text-right font-mono text-xs", position.unrealizedPnlPct >= 0 ? "text-success" : "text-destructive")}>
                  {position.unrealizedPnlPct >= 0 ? "+" : ""}{position.unrealizedPnlPct.toFixed(2)}%
                </TableCell>
                <TableCell className={cn("numeric px-4 py-3.5 text-right font-mono text-xs", position.realizedPnl >= 0 ? "text-success" : "text-destructive")}>
                  {position.realizedPnl >= 0 ? "+" : "−"}{currencySymbol}{Math.abs(position.realizedPnl).toFixed(2)}
                </TableCell>
                <TableCell className="px-4 py-3.5 text-xs capitalize text-muted-foreground">{position.strategy}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}

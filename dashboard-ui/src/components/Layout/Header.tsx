"use client"

import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Bell, Moon, Search, Sun } from "lucide-react"

interface HeaderProps {
  unreadAlerts?: number
  isDarkMode?: boolean
  onToggleDarkMode?: () => void
  user?: {
    name: string
    email: string
  }
}

export function Header({
  unreadAlerts = 0,
  isDarkMode = true,
  onToggleDarkMode,
  user = { name: "Trader", email: "trader@alpha.local" },
}: HeaderProps) {
  const navigate = useNavigate()
  const [searchQuery, setSearchQuery] = useState("")

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const query = searchQuery.trim()
    navigate(query ? `/fundamentals?search=${encodeURIComponent(query)}` : "/fundamentals")
  }

  return (
    <header className="sticky top-0 z-20 h-[72px] border-b border-border/70 bg-background/80 backdrop-blur-xl">
      <div className="flex h-full items-center gap-3 pl-14 pr-4 sm:pl-4 sm:pr-6 lg:pl-8 lg:pr-8">
        <form
          role="search"
          onSubmit={submitSearch}
          className="group flex h-11 w-11 shrink-0 items-center rounded-lg border border-border/70 bg-muted/35 transition-all hover:border-primary/30 hover:bg-muted/60 focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-ring/30 sm:w-64"
        >
          <Search className="ml-3 hidden h-4 w-4 shrink-0 text-muted-foreground sm:block" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            className="hidden min-w-0 flex-1 bg-transparent px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground sm:block"
            placeholder="Search fundamentals"
            aria-label="Search fundamentals"
          />
          <button
            type="submit"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:text-foreground sm:hidden"
            aria-label="Search fundamentals"
          >
            <Search className="h-4 w-4" />
          </button>
        </form>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <Link
            to="/alerts"
            className="relative inline-flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={`Alerts${unreadAlerts > 0 ? ` (${unreadAlerts} unread)` : ""}`}
          >
            <Bell className="h-[18px] w-[18px]" />
            {unreadAlerts > 0 && (
              <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold text-destructive-foreground ring-2 ring-background">
                {unreadAlerts > 9 ? "9+" : unreadAlerts}
              </span>
            )}
          </Link>

          <button
            type="button"
            onClick={onToggleDarkMode}
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={isDarkMode ? "Switch to light mode" : "Switch to dark mode"}
          >
            {isDarkMode ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
          </button>

          <div className="mx-1 hidden h-5 w-px bg-border sm:block" />

          <div className="flex items-center gap-2 rounded-lg px-1.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/20">
              {user.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="hidden text-left md:block">
              <p className="text-xs font-semibold leading-none text-foreground">{user.name}</p>
              <p className="mt-1 text-[10px] leading-none text-muted-foreground">Paper workspace</p>
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}

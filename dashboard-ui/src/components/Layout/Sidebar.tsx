"use client"

import * as React from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import {
  Bell,
  Folder,
  HeartPulse,
  LayoutDashboard,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldAlert,
  TrendingUp,
  Wallet,
  X,
} from "lucide-react"
import {
  Dialog,
  DialogOverlay,
  DialogPortal,
  DialogPrimitive,
  DialogTrigger,
} from "@/components/ui/dialog"

const navigationGroups = [
  {
    label: "Workspace",
    items: [
      { name: "Dashboard", href: "/", icon: LayoutDashboard },
    ],
  },
  {
    label: "Trading",
    items: [
      { name: "Positions", href: "/positions", icon: Wallet },
      { name: "Alerts", href: "/alerts", icon: Bell },
      { name: "Performance", href: "/performance", icon: TrendingUp },
      { name: "Risk", href: "/risk", icon: ShieldAlert },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { name: "Sessions", href: "/sessions", icon: MessageCircle },
      { name: "Fundamentals", href: "/fundamentals", icon: Folder },
    ],
  },
  {
    label: "Operations",
    items: [
      { name: "System Health", href: "/health", icon: HeartPulse },
      { name: "Settings", href: "/settings", icon: Settings },
    ],
  },
]

function AlphaMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M16 3 28 9.5v13L16 29 4 22.5v-13L16 3Z" fill="currentColor" fillOpacity="0.14" stroke="currentColor" strokeWidth="1.5" />
      <path d="m9.5 20 6.5-11 6.5 11h-4l-2.5-4.3L13.5 20H9.5Z" fill="currentColor" />
    </svg>
  )
}

interface SidebarContentProps {
  collapsed: boolean
  mobile?: boolean
  onToggleCollapsed?: () => void
  onNavigate?: () => void
}

function SidebarContent({ collapsed, mobile = false, onToggleCollapsed, onNavigate }: SidebarContentProps) {
  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-[72px] shrink-0 items-center border-b border-border/70 px-4", collapsed && !mobile && "lg:justify-center lg:px-2")}>
        <NavLink to="/" onClick={onNavigate} className="flex min-w-0 items-center gap-3" aria-label="Alpha dashboard">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-inset ring-primary/25">
            <AlphaMark className="h-6 w-6" />
          </div>
          {(!collapsed || mobile) && (
            <div className="min-w-0">
              <p className="font-display text-[15px] font-semibold leading-4 tracking-[0.16em] text-foreground">ALPHA</p>
              <p className="mt-1 text-[9px] font-semibold tracking-[0.22em] text-muted-foreground">TRADING OS</p>
            </div>
          )}
        </NavLink>
        {mobile ? (
          <DialogPrimitive.Close asChild>
            <button
              type="button"
              className="ml-auto inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label="Close navigation"
            >
              <X className="h-5 w-5" />
            </button>
          </DialogPrimitive.Close>
        ) : (
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="ml-auto hidden h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:inline-flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-2 py-5" aria-label="Main navigation">
        {navigationGroups.map((group) => (
          <div key={group.label}>
            {(!collapsed || mobile) && <p className="section-eyebrow mb-2 px-3">{group.label}</p>}
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.name}
                  to={item.href}
                  end={item.href === "/"}
                  onClick={onNavigate}
                  className={({ isActive }) => cn(
                    "group flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-all duration-200",
                    isActive
                      ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/15"
                      : "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
                    collapsed && !mobile && "lg:justify-center lg:px-2",
                  )}
                  title={collapsed && !mobile ? item.name : undefined}
                >
                  <item.icon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                  {(!collapsed || mobile) && <span className="truncate">{item.name}</span>}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className={cn("shrink-0 border-t border-border/70 p-3", collapsed && !mobile && "lg:p-2")}>
        <div className={cn("flex items-center gap-3 rounded-xl bg-muted/55 p-3", collapsed && !mobile && "lg:justify-center lg:p-2")}>
          <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary ring-1 ring-inset ring-primary/20">
            <AlphaMark className="h-5 w-5" />
            <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-card bg-success" />
          </div>
          {(!collapsed || mobile) && (
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold text-foreground">Trading Bot</p>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">Paper workspace</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = React.useState(false)
  const [isMobileOpen, setIsMobileOpen] = React.useState(false)

  return (
    <>
      <Dialog open={isMobileOpen} onOpenChange={setIsMobileOpen}>
        <DialogTrigger asChild>
          <button
            type="button"
            className="fixed left-3 top-3 z-40 inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-card/90 text-foreground shadow-lg backdrop-blur-xl transition-colors hover:bg-accent lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
        </DialogTrigger>
        <DialogPortal>
          <DialogOverlay className="bg-black/65 backdrop-blur-sm" />
          <DialogPrimitive.Content aria-modal="true" className="fixed inset-y-0 left-0 z-50 h-dvh w-72 max-w-[85vw] border-r border-border/80 bg-card/95 shadow-2xl backdrop-blur-xl focus:outline-none">
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">Alpha trading dashboard navigation</DialogPrimitive.Description>
            <SidebarContent collapsed={false} mobile onNavigate={() => setIsMobileOpen(false)} />
          </DialogPrimitive.Content>
        </DialogPortal>
      </Dialog>

      <aside
        id="dashboard-sidebar"
        className={cn(
          "sticky top-0 z-30 hidden h-dvh shrink-0 flex-col border-r border-border/80 bg-card/85 backdrop-blur-xl lg:flex",
          isCollapsed ? "lg:w-16" : "lg:w-64",
        )}
      >
        <SidebarContent collapsed={isCollapsed} onToggleCollapsed={() => setIsCollapsed((value) => !value)} />
      </aside>
    </>
  )
}

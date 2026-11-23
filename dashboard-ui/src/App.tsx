import { lazy, Suspense, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ToastProviderWrapper } from '@/components/ToastProvider'
import { Sidebar } from '@/components/Layout/Sidebar'
import { Header } from '@/components/Layout/Header'
import { PageLoading } from '@/components/PageState'
import { SessionList } from '@/components/Sessions/SessionList'
import { SessionDetail } from '@/components/Sessions/SessionDetail'
import { FundamentalsTable } from '@/components/Fundamentals/FundamentalsTable'
import { FundamentalsFilter } from '@/components/Fundamentals/FundamentalsFilter'
import { FundamentalsCard } from '@/components/Fundamentals/FundamentalsCard'
import { ServiceStatusGrid } from '@/components/SystemHealth/ServiceStatusGrid'
import { LaunchdJobsTable } from '@/components/SystemHealth/LaunchdJobsTable'
import { ResourceMetricsCharts } from '@/components/SystemHealth/ResourceMetricsCharts'
import { fleetApi } from '@/lib/api'
import { alertId } from '@/lib/alerts'
import { refetchKeys } from '@/lib/query-client'

const DashboardPage = lazy(() => import('@/app/page'))
const PositionsPage = lazy(() => import('@/pages/PositionsPage'))
const AlertsPage = lazy(() => import('@/pages/AlertsPage'))
const PerformancePage = lazy(() => import('@/pages/PerformancePage'))
const RiskPage = lazy(() => import('@/pages/RiskPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))

export default function App() {
  const [isDarkMode, setIsDarkMode] = useState(() => window.localStorage.getItem('alpha-theme') !== 'light')
  const [acknowledgedAlertIds, setAcknowledgedAlertIds] = useState<string[]>([])
  const alertsQuery = useQuery({
    queryKey: refetchKeys.alerts,
    queryFn: fleetApi.alerts,
    refetchInterval: 60_000,
  })

  const unreadAlerts = (alertsQuery.data ?? []).filter(
    (alert, index) => !acknowledgedAlertIds.includes(alertId(alert, index)),
  ).length

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDarkMode)
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', isDarkMode ? '#070b14' : '#f4f7fb')
  }, [isDarkMode])

  const setTheme = (dark: boolean) => {
    setIsDarkMode(dark)
    document.documentElement.classList.toggle('dark', dark)
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#070b14' : '#f4f7fb')
    window.localStorage.setItem('alpha-theme', dark ? 'dark' : 'light')
  }

  const acknowledgeAlert = (id: string) => {
    setAcknowledgedAlertIds((current) => current.includes(id) ? current : [...current, id])
  }

  return (
    <ToastProviderWrapper>
      <div className="min-h-screen bg-background lg:flex">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header
            unreadAlerts={unreadAlerts}
            isDarkMode={isDarkMode}
            onToggleDarkMode={() => setTheme(!isDarkMode)}
            user={{ name: 'Trader', email: 'trader@alpha.local' }}
          />
          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Suspense fallback={<PageLoading cards={4} />}>
              <Routes>
              <Route path="/" element={<DashboardPage acknowledgedAlertIds={acknowledgedAlertIds} onAcknowledge={acknowledgeAlert} />} />
              <Route path="/portfolio" element={<Navigate to="/positions" replace />} />
              <Route path="/positions" element={<PositionsPage />} />
              <Route path="/risk" element={<RiskPage acknowledgedAlertIds={acknowledgedAlertIds} onAcknowledge={acknowledgeAlert} />} />
              <Route path="/alerts" element={<AlertsPage acknowledgedAlertIds={acknowledgedAlertIds} onAcknowledge={acknowledgeAlert} />} />
              <Route path="/performance" element={<PerformancePage />} />
              <Route path="/settings" element={<SettingsPage isDarkMode={isDarkMode} onToggleTheme={setTheme} />} />
              <Route path="/sessions" element={<SessionList />} />
              <Route path="/sessions/:provider/:id" element={<SessionDetail />} />
              <Route path="/fundamentals" element={<FundamentalsTable />} />
              <Route path="/fundamentals/filter" element={<FundamentalsFilter />} />
              <Route path="/fundamentals/:symbol" element={<FundamentalsCard />} />
              <Route path="/health" element={<ServiceStatusGrid />} />
              <Route path="/health/launchd" element={<LaunchdJobsTable />} />
              <Route path="/health/resources" element={<ResourceMetricsCharts />} />
              <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </div>
    </ToastProviderWrapper>
  )
}

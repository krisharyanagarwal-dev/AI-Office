import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10000,
      refetchOnWindowFocus: false,
      retry: false,
    },
  },
})

export const refetchKeys = {
  sessions: ['sessions'],
  fleet: ['fleet'],
  alerts: ['alerts'],
  portfolio: ['portfolio'],
  performance: ['performance'],
  risk: ['risk'],
  settings: ['settings'],
  fundamentals: ['fundamentals'],
  health: ['health'],
}

export const manualRefetch = {
  sessions: () => queryClient.invalidateQueries({ queryKey: refetchKeys.sessions }),
  fleet: () => queryClient.invalidateQueries({ queryKey: refetchKeys.fleet }),
  alerts: () => queryClient.invalidateQueries({ queryKey: refetchKeys.alerts }),
  portfolio: () => queryClient.invalidateQueries({ queryKey: refetchKeys.portfolio }),
  performance: () => queryClient.invalidateQueries({ queryKey: refetchKeys.performance }),
  risk: () => queryClient.invalidateQueries({ queryKey: refetchKeys.risk }),
  settings: () => queryClient.invalidateQueries({ queryKey: refetchKeys.settings }),
  fundamentals: () => queryClient.invalidateQueries({ queryKey: refetchKeys.fundamentals }),
  health: () => queryClient.invalidateQueries({ queryKey: refetchKeys.health }),
}

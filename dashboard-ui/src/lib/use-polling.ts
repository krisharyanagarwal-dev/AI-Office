import { useEffect, useRef, useState } from 'react'

export interface UsePollingOptions<T> {
  fetch: (signal: AbortSignal) => Promise<T>
  interval: number
  onSuccess?: (data: T) => void
  onError?: (error: Error) => void
  maxFailureCount?: number
  baseDelay?: number
  maxDelay?: number
  immediate?: boolean
}

export interface UsePollingReturn<T> {
  data: T | null
  isLoading: boolean
  isError: boolean
  error: Error | null
  failureCount: number
  retry: () => void
}

/**
 * Polls a fetch function on an interval with:
 * - one AbortController per attempt (aborted on unmount, retry, or replacement)
 * - visibility-aware pausing (stops when hidden, refetchs on visible)
 * - exponential backoff on failures, capped at maxDelay
 * - a hard stop after maxFailureCount consecutive failures until retry() is called
 */
export function usePolling<T>({
  fetch,
  interval,
  onSuccess,
  onError,
  maxFailureCount = 5,
  baseDelay = 1_000,
  maxDelay = 30_000,
  immediate = true,
}: UsePollingOptions<T>): UsePollingReturn<T> {
  const [data, setData] = useState<T | null>(null)
  const [isLoading, setIsLoading] = useState(immediate)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [failureCount, setFailureCount] = useState(0)

  const controllerRef = useRef<AbortController | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const performFetchRef = useRef<(() => Promise<void>) | null>(null)
  const backoffRef = useRef(0)
  const failureCountRef = useRef(0)
  const fetchRef = useRef(fetch)
  const onSuccessRef = useRef(onSuccess)
  const onErrorRef = useRef(onError)

  fetchRef.current = fetch
  onSuccessRef.current = onSuccess
  onErrorRef.current = onError
  failureCountRef.current = failureCount

  const abortCurrent = () => {
    const controller = controllerRef.current
    if (controller) {
      controller.abort()
      controllerRef.current = null
    }
  }

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const performFetch = async () => {
    abortCurrent()
    const controller = new AbortController()
    controllerRef.current = controller

    try {
      setIsLoading(true)
      const result = await fetchRef.current(controller.signal)

      if (controller.signal.aborted) return

      setData(result)
      setIsError(false)
      setError(null)
      setFailureCount(0)
      backoffRef.current = 0
      failureCountRef.current = 0
      onSuccessRef.current?.(result)

      schedule(interval)
    } catch (caught) {
      if (controller.signal.aborted) return

      const thrown = caught instanceof Error ? caught : new Error(String(caught))
      setIsError(true)
      setError(thrown)
      onErrorRef.current?.(thrown)

      const count = failureCountRef.current + 1
      failureCountRef.current = count
      setFailureCount(count)

      if (count >= maxFailureCount) {
        // Hard stop: suspend polling until the user retries.
        return
      }

      backoffRef.current = count
      const delay = Math.min(baseDelay * Math.pow(2, count - 1), maxDelay)
      schedule(delay)
    } finally {
      if (!controller.signal.aborted && controllerRef.current === controller) {
        setIsLoading(false)
      }
    }
  }

  performFetchRef.current = performFetch

  const schedule = (delay: number) => {
    clearTimer()
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      performFetchRef.current?.()
    }, delay)
  }

  const retry = () => {
    abortCurrent()
    clearTimer()
    setFailureCount(0)
    failureCountRef.current = 0
    backoffRef.current = 0
    setError(null)
    setIsError(false)
    setIsLoading(true)
    performFetch()
  }

  useEffect(() => {
    if (immediate) performFetch()
    return () => {
      abortCurrent()
      clearTimer()
    }
  }, [immediate])

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        performFetchRef.current?.()
      } else {
        clearTimer()
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [])

  return { data, isLoading, isError, error, failureCount, retry }
}

import { useEffect, useRef, useState } from 'react'

export interface UseWebSocketOptions {
  url: string
  onMessage?: (event: MessageEvent) => void
  onOpen?: () => void
  onClose?: () => void
  reconnectInterval?: number
}

export function useWebSocket({
  url,
  onMessage,
  onOpen,
  onClose,
  reconnectInterval = 30_000,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<number | null>(null)

  const connect = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    wsRef.current = new WebSocket(url)

    wsRef.current.onopen = () => {
      setIsConnected(true)
      onOpen?.()
    }

    wsRef.current.onmessage = (event) => {
      setLastMessage(event.data)
      onMessage?.(event)
    }

    wsRef.current.onclose = () => {
      setIsConnected(false)
      onClose?.()
      // Schedule reconnection
      reconnectRef.current = window.setTimeout(connect, reconnectInterval)
    }

    wsRef.current.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }

  const disconnect = () => {
    if (reconnectRef.current !== null) {
      clearTimeout(reconnectRef.current)
      reconnectRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsConnected(false)
  }

  useEffect(() => {
    connect()
    return () => {
      disconnect()
    }
  }, [url])

  return { isConnected, lastMessage, disconnect }
}
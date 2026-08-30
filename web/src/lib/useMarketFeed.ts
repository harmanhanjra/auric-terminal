import { useEffect, useRef, useState } from 'react'
import type { Quote } from './types'

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/market`
}

export interface UseMarketFeedResult {
  tick: Quote | null
  status: 'connecting' | 'open' | 'closed' | 'delayed' | 'live'
}

export function useMarketFeed(intervalMs = 4000): UseMarketFeedResult {
  const [tick, setTick] = useState<Quote | null>(null)
  const [status, setStatus] = useState<UseMarketFeedResult['status']>('connecting')
  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(1000)
  const lastTickRef = useRef(0)

  useEffect(() => {
    let closed = false
    const connect = () => {
      const socket = new WebSocket(wsUrl())
      socketRef.current = socket

      socket.onopen = () => {
        retryRef.current = 1000
        setStatus('open')
        socket.send('ready')
      }

      socket.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data)
          if (m.type === 'tick') {
            lastTickRef.current = Date.now()
            setTick(m as Quote)
            setStatus('live')
          }
        } catch {
          /* ignore malformed frame */
        }
      }

      socket.onclose = () => {
        setStatus((s) => (s === 'live' ? s : 'connecting'))
        if (!closed) {
          setTimeout(connect, retryRef.current)
          retryRef.current = Math.min(15000, retryRef.current * 1.8)
        }
      }

      socket.onerror = () => socket.close()
    }

    connect()

    const poll = () => {
      if (lastTickRef.current && Date.now() - lastTickRef.current > 12000) {
        setStatus('delayed')
      }
    }

    const pollId = window.setInterval(poll, intervalMs)
    return () => {
      closed = true
      window.clearInterval(pollId)
      socketRef.current?.close()
    }
  }, [intervalMs])

  return { tick, status }
}

export function usePollingQuery<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  intervalMs: number,
  onError?: (e: unknown) => void,
): T | null {
  const [data, setData] = useState<T | null>(null)

  useEffect(() => {
    let active = true
    const run = async () => {
      try {
        const result = await fetcher()
        if (active) setData(result)
      } catch (e) {
        onError?.(e)
      }
    }
    run()
    const id = window.setInterval(run, intervalMs)
    return () => {
      active = false
      window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return data
}
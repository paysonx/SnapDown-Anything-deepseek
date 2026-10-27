import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import type { Snapshot } from './types'

/**
 * 订阅后端 SSE 快照。
 * - 首帧由 EventSource 主动推送，页面刷新后自动恢复全部任务；
 * - 断线由 EventSource 自带重连（服务端 retry: 2000）；
 * - 标签页重新可见时补一次 HTTP 快照，避免后台被节流导致的旧状态。
 */
export function useSnapshot() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const mounted = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const next = await api.listTasks()
      if (mounted.current) {
        setSnapshot(next)
        setLoadError(null)
      }
    } catch (error) {
      if (mounted.current) setLoadError((error as Error).message)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void refresh()

    const source = new EventSource('/api/events')
    const onOpen = () => setConnected(true)
    const onError = () => setConnected(false)
    const onSnapshot = (event: MessageEvent<string>) => {
      try {
        const next = JSON.parse(event.data) as Snapshot
        if (mounted.current) {
          setSnapshot(next)
          setConnected(true)
          setLoadError(null)
        }
      } catch {
        // 忽略坏帧，等待下一次推送
      }
    }

    source.addEventListener('open', onOpen)
    source.addEventListener('error', onError)
    source.addEventListener('snapshot', onSnapshot as EventListener)

    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)

    return () => {
      mounted.current = false
      source.removeEventListener('open', onOpen)
      source.removeEventListener('error', onError)
      source.removeEventListener('snapshot', onSnapshot as EventListener)
      source.close()
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [refresh])

  return { snapshot, connected, loadError, refresh }
}

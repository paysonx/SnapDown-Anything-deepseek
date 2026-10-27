import { useEffect, useState } from 'react'

/** 轻量计时器：intervalMs <= 0 时停止刷新，用于倒计时等只在需要时跳动的地方。 */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (intervalMs <= 0) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])

  return now
}

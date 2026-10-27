import { formatCountdown } from '../lib/format'
import { useNow } from '../lib/useNow'

/** 平台冷却倒计时：视觉上每 250ms 跳动，读屏只播报一次「平台冷却中」。 */
export function Countdown({ until }: { until: number | null }) {
  const now = useNow(until ? 250 : 0)
  if (!until) return null
  const remaining = until - now / 1000
  return (
    <>
      <span aria-hidden="true">{formatCountdown(remaining)}</span>
      <span className="sr-only">平台冷却中</span>
    </>
  )
}

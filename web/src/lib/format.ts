/** 展示层数字格式化：只做展示，不改变任何真实数值。 */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

export function formatBytes(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value) || value < 0) return '—'
  if (value < 1024) return `${Math.round(value)} B`
  let size = value
  let unit = 0
  while (size >= 1024 && unit < UNITS.length - 1) {
    size /= 1024
    unit += 1
  }
  const rounded = size >= 100 ? size.toFixed(0) : size.toFixed(digits)
  return `${rounded} ${UNITS[unit]}`
}

export function formatSpeed(bps: number | null | undefined): string {
  if (!bps || bps <= 0) return '—'
  return `${formatBytes(bps)}/s`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) {
    return '—'
  }
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function formatEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return '—'
  }
  if (seconds < 1) return '不到 1 秒'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60)
    const s = Math.round(seconds % 60)
    return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分`
  }
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m > 0 ? `${h} 小时 ${m} 分` : `${h} 小时`
}

export function formatCountdown(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '即将开始'
  if (seconds < 10) return `${seconds.toFixed(1)} 秒`
  return `${Math.ceil(seconds)} 秒`
}

/** 只在数值有效时返回百分比，避免把未知大小伪装成 0%。 */
export function clampPercent(value: number | null | undefined): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null
  return Math.min(100, Math.max(0, value))
}

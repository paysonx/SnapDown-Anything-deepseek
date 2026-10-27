import type { TaskStatus } from '../lib/types'

const TONE: Record<TaskStatus, string> = {
  resolve_queued: 'wait',
  resolving: 'busy',
  awaiting_selection: 'wait',
  download_queued: 'wait',
  downloading: 'busy',
  merging: 'busy',
  completed: 'success',
  failed: 'danger',
  cancelled: 'muted',
  interrupted: 'warn',
}

export function StatusPill({ status, label }: { status: TaskStatus; label: string }) {
  return (
    <span className={`pill pill-${TONE[status]}`}>
      <span className="pill-dot" aria-hidden="true" />
      {label}
    </span>
  )
}

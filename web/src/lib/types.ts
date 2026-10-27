/**
 * 与后端 app/models.py 的 to_api() 对齐的接口类型。
 * 只声明前端真正用到的字段，避免与后端实现漂移时静默出错。
 */

export type TaskStatus =
  | 'resolve_queued'
  | 'resolving'
  | 'awaiting_selection'
  | 'download_queued'
  | 'downloading'
  | 'merging'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export type Route = 'direct' | 'proxy'

export interface StreamProgress {
  kind: 'video' | 'audio' | 'single' | string
  label: string
  downloaded_bytes: number
  total_bytes: number | null
  percent: number | null
  done: boolean
}

export interface Progress {
  phase: string | null
  downloaded_bytes: number
  total_bytes: number | null
  total_estimated: boolean
  percent: number | null
  speed_bps: number | null
  eta_s: number | null
  streams: StreamProgress[]
  updated_at: number
}

export interface QualityOption {
  id: string
  label: string
  detail: string
  selector: string
  height: number | null
  ext: string | null
  fps: number | null
  size_bytes: number | null
  is_best: boolean
}

export interface QueueInfo {
  state: 'running' | 'queued'
  position: number
  queue_size: number
  cooldown_seconds: number
  cooldown_until: number | null
  eta_start_s: number | null
}

export interface TaskError {
  code: string
  message: string
}

export interface Task {
  id: string
  url: string
  platform: string
  platform_label: string
  route: Route
  status: TaskStatus
  status_label: string
  status_reason: string | null
  title: string | null
  duration_s: number | null
  uploader: string | null
  options: QualityOption[]
  selected_option: string | null
  selected_selector: string | null
  progress: Progress
  error: TaskError | null
  can: {
    select: boolean
    cancel: boolean
    retry: boolean
    save: boolean
  }
  retryable: boolean
  output_name: string | null
  output_size: number | null
  attempts: number
  created_at: number
  updated_at: number
  started_at: number | null
  finished_at: number | null
  queue: QueueInfo | null
}

export interface LaneSnapshot {
  platform: string
  running: boolean
  queued: number
  cooldown_seconds: number
  cooldown_remaining_s: number
  cooldown_until: number | null
}

export interface ProxyCandidate {
  name: string
  url: string
  healthy: boolean
}

export interface ProxyStatus {
  mode: string
  probe_url: string
  candidates: ProxyCandidate[]
  selected: string | null
  available: boolean
}

export interface Limits {
  max_active_tasks: number
  file_ttl_hours: number
  cooldowns: Record<string, number>
}

export interface Snapshot {
  type: 'snapshot'
  tasks: Task[]
  platforms: Record<string, LaneSnapshot>
  proxy: ProxyStatus | null
  limits: Limits
  server_time: number
}

/** 后端错误响应体：{"error": {"code", "message", "retryable"}} */
export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    retryable?: boolean
  }
}

import { api } from '../lib/api'
import { formatBytes, formatDuration } from '../lib/format'
import type { Task } from '../lib/types'
import { IconAlert, IconCheck, IconDownload, IconFilm, IconRetry, IconSpinner } from './icons'
import { StatusPill } from './StatusPill'

export function CompletedCard({ task, ttlHours }: { task: Task; ttlHours: number }) {
  const option = task.options.find((item) => item.id === task.selected_option)
  const detail = option ? `${option.label} · ${option.detail}` : '保留源画质'
  // 服务端保存时用标题做文件名（见 app/api.py），这里保持一致
  const ext = (task.output_name ?? 'video.mp4').split('.').pop() || 'mp4'
  const fileName = `${(task.title ?? '视频文件').replace(/[\\/:*?"<>|]/g, '_').slice(0, 80)}.${ext}`

  return (
    <article className="surface result-card">
      <div className="card-head">
        <div className="chip-row">
          <StatusPill status={task.status} label={task.status_label} />
          <span className="chip">{task.platform_label}</span>
        </div>
      </div>

      <p className="result-title">{task.title ?? task.output_name}</p>

      <div className="file-box">
        <span className="file-icon" aria-hidden="true">
          <IconFilm />
        </span>
        <div className="file-body">
          <span className="file-name">{fileName}</span>
          <span className="file-meta">
            {detail} · {formatBytes(task.output_size)} · 时长 {formatDuration(task.duration_s)}
          </span>
          <span className="file-check">
            <IconCheck className="file-check-icon" />
            已通过文件校验
          </span>
        </div>
      </div>

      <div className="card-foot">
        <p className="foot-note">服务端保留 {ttlHours} 小时后自动清理</p>
        <a className="btn btn-primary" href={api.fileUrl(task.id)} download>
          <IconDownload className="btn-icon" />
          保存到设备
        </a>
      </div>
    </article>
  )
}

interface FailedCardProps {
  task: Task
  busy: boolean
  onRetry: () => void
}

const CLEANUP_NOTE: Partial<Record<Task['status'], string>> = {
  failed: '失败后的临时文件已清理，可直接重试。',
  cancelled: '已取消，临时文件已清理。',
  interrupted: '服务异常导致中断；重试会复用已下载的分片继续，不会从头再来。',
}

export function FailedCard({ task, busy, onRetry }: FailedCardProps) {
  const message = task.error?.message || task.status_reason || '任务未完成'
  const note = CLEANUP_NOTE[task.status]

  return (
    <article className="surface result-card">
      <div className="card-head">
        <div className="chip-row">
          <StatusPill status={task.status} label={task.status_label} />
          <span className="chip">{task.platform_label}</span>
        </div>
      </div>

      <p className="result-title">{task.title ?? task.url}</p>

      <div className={task.status === 'cancelled' ? 'banner banner-neutral' : 'banner banner-error'}>
        <IconAlert className="banner-icon" />
        <p className="banner-text">{message}</p>
      </div>

      <div className="card-foot">
        <p className="foot-note">{note ?? '可以重新解析后再试。'}</p>
        {task.can.retry ? (
          <button className="btn btn-ghost" type="button" onClick={onRetry} disabled={busy}>
            {busy ? <IconSpinner className="btn-icon" /> : <IconRetry className="btn-icon" />}
            重试
          </button>
        ) : null}
      </div>
    </article>
  )
}

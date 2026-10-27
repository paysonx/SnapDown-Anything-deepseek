import { useMemo } from 'react'

import { clampPercent, formatBytes, formatEta, formatSpeed } from '../lib/format'
import type { Task } from '../lib/types'
import { Countdown } from './Countdown'
import { IconClose, IconSpinner } from './icons'
import { StatusPill } from './StatusPill'
import { Stepper, type Step } from './Stepper'

interface TaskProgressProps {
  task: Task
  busy: boolean
  onCancel: () => void
}

function buildSteps(task: Task): Step[] {
  const { progress, status } = task
  const streams = progress.streams
  if (streams.length === 0) return []

  const merging = status === 'merging'
  const steps: Step[] = streams.map((stream) => ({
    id: stream.kind,
    label: stream.label,
    state: stream.done || merging ? 'done' : 'active',
    percent: stream.percent,
  }))

  // 视频流 + 音频流分开下载时，补一个无损合并阶段，避免两条流都显示「完成」就算结束。
  if (streams.length >= 2) {
    steps.push({ id: 'merge', label: '无损合并', state: merging ? 'active' : 'todo' })
  }
  return steps
}

export function TaskProgress({ task, busy, onCancel }: TaskProgressProps) {
  const { progress, status, queue } = task
  const merging = status === 'merging'
  const steps = useMemo(() => buildSteps(task), [task])

  const selectedOption = task.options.find((item) => item.id === task.selected_option)
  const percent = clampPercent(progress.percent)
  const total = progress.total_bytes
  const downloaded = progress.downloaded_bytes
  const determinate = merging || percent !== null
  const barWidth = merging ? 100 : (percent ?? 0)

  const stats = merging
    ? [
        { label: '已下载', value: formatBytes(downloaded) },
        { label: '合并方式', value: '无损封装' },
        { label: '剩余时间', value: '合并中' },
      ]
    : [
        {
          label: '已下载',
          value: total ? `${formatBytes(downloaded)} / ${formatBytes(total)}` : formatBytes(downloaded),
        },
        { label: '速度', value: formatSpeed(progress.speed_bps) },
        {
          label: '剩余时间',
          value: progress.eta_s !== null ? formatEta(progress.eta_s) : percent === null ? '估算中' : '即将完成',
        },
      ]

  return (
    <div className="surface">
      <div className="card-head">
        <div className="chip-row">
          <StatusPill status={status} label={task.status_label} />
          <span className="chip">{task.platform_label}</span>
          <span className="chip chip-route chip-route-direct">
            {task.route === 'proxy' ? '仅走代理' : '直连'}
          </span>
        </div>
        {task.can.cancel ? (
          <button className="btn btn-ghost btn-sm" type="button" onClick={onCancel} disabled={busy}>
            <IconClose className="btn-icon" />
            取消任务
          </button>
        ) : null}
      </div>

      <h2 className="task-title">{task.title ?? task.url}</h2>
      <p className="video-meta">
        <span>{task.status_reason ?? '处理中'}</span>
        {selectedOption ? (
          <>
            <span aria-hidden="true">·</span>
            <span>{selectedOption.label}</span>
          </>
        ) : null}
      </p>

      {status === 'resolving' ? (
        <p className="inline-loading">
          <IconSpinner className="inline-icon" />
          正在读取标题、时长与可用清晰度，通常需要几秒钟
        </p>
      ) : null}

      {steps.length > 0 ? <Stepper steps={steps} /> : null}

      {status === 'downloading' || merging ? (
        <>
          <div className="metric">
            {merging ? (
              <span className="metric-word">合并中</span>
            ) : percent !== null ? (
              <span className="metric-value">
                {Math.floor(percent)}
                <span className="metric-unit">%</span>
              </span>
            ) : (
              <span className="metric-value metric-value-sm">已下载 {formatBytes(downloaded)}</span>
            )}
            <span className="metric-note">
              {merging
                ? '音视频下载完成，正在无损合并'
                : total
                  ? `共 ${formatBytes(total)}${progress.total_estimated ? '（估算）' : ''}`
                  : '总大小未知，按实际下载量展示'}
            </span>
          </div>

          <div
            className={`progress-track ${determinate ? '' : 'is-indeterminate'} ${merging ? 'is-merging' : ''}`}
            role="progressbar"
            aria-label="下载进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={determinate ? Math.round(barWidth) : undefined}
            aria-valuetext={
              merging
                ? '正在无损合并'
                : percent !== null
                  ? `${Math.floor(percent)}%`
                  : `总大小未知，已下载 ${formatBytes(downloaded)}`
            }
          >
            <div
              className="progress-fill"
              style={determinate ? { width: `${barWidth}%` } : undefined}
            />
          </div>

          <dl className="stats">
            {stats.map((item) => (
              <div className="stat" key={item.label}>
                <dt className="stat-label">{item.label}</dt>
                <dd className="stat-value">{item.value}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}

      {queue ? (
        <p className="queue-line">
          {queue.state === 'running' ? (
            '正在使用该平台额度'
          ) : (
            <>
              队列第 {queue.position} 位 · 共 {queue.queue_size} 个任务
              {queue.cooldown_until ? (
                <>
                  {' '}
                  · 平台冷却 <Countdown until={queue.cooldown_until} /> 后释放额度
                </>
              ) : queue.eta_start_s !== null ? (
                ` · 预计 ${Math.round(queue.eta_start_s)} 秒后开始`
              ) : null}
            </>
          )}
        </p>
      ) : null}

      <p className="foot-note foot-note-quiet">
        服务端任务 · 关闭页面也会继续下载，进度通过 SSE 每秒回传
      </p>
    </div>
  )
}

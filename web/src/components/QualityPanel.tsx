import { useEffect, useMemo, useState } from 'react'

import { formatBytes, formatDuration } from '../lib/format'
import type { Task } from '../lib/types'
import { IconDownload, IconSpinner } from './icons'

interface QualityPanelProps {
  task: Task
  busy: boolean
  onStart: (optionId: string) => void
  onCancel: () => void
}

export function QualityPanel({ task, busy, onStart, onCancel }: QualityPanelProps) {
  const options = task.options
  const fallback = useMemo(() => options.find((item) => item.is_best) ?? options[0], [options])
  const [selected, setSelected] = useState<string>(task.selected_option ?? fallback?.id ?? '')

  useEffect(() => {
    if (!options.some((item) => item.id === selected)) {
      setSelected(fallback?.id ?? '')
    }
  }, [options, selected, fallback])

  const groupName = `quality-${task.id}`

  return (
    <div className="surface">
      <div className="card-head">
        <div className="chip-row">
          <span className="chip">{task.platform_label}</span>
          <span className={`chip chip-route chip-route-${task.route === 'proxy' ? 'proxy' : 'direct'}`}>
            {task.route === 'proxy' ? '仅走代理' : '直连'}
          </span>
        </div>
      </div>

      <h2 className="video-title">{task.title ?? task.url}</h2>
      <p className="video-meta">
        <span>时长 {formatDuration(task.duration_s)}</span>
        <span aria-hidden="true">·</span>
        <span>{options.length} 个可选清晰度</span>
        {task.uploader ? (
          <>
            <span aria-hidden="true">·</span>
            <span className="video-uploader">{task.uploader}</span>
          </>
        ) : null}
      </p>

      <fieldset className="quality-fieldset" disabled={busy}>
        <legend className="sr-only">选择清晰度</legend>
        <div className="quality-list">
          {options.map((option) => {
            const checked = option.id === selected
            return (
              <label
                key={option.id}
                className={`quality-row ${checked ? 'is-selected' : ''} ${option.is_best ? 'is-best' : ''}`}
                data-option={option.id}
              >
                <input
                  className="quality-input"
                  type="radio"
                  name={groupName}
                  value={option.id}
                  checked={checked}
                  onChange={() => setSelected(option.id)}
                />
                <span className="quality-mark" aria-hidden="true" />
                <span className="quality-head">
                  <span className="quality-label">{option.label}</span>
                  {option.is_best ? <span className="quality-badge">默认</span> : null}
                </span>
                <span className="quality-size">
                  {option.size_bytes ? `约 ${formatBytes(option.size_bytes, 0)}` : '大小未知'}
                </span>
                <span className="quality-detail">{option.detail}</span>
              </label>
            )
          })}
        </div>
      </fieldset>

      <div className="card-foot card-foot--sticky">
        <p className="foot-note">保留源画质 · 音视频无损合并，不重新编码</p>
        <div className="foot-actions">
          <button className="btn btn-ghost" type="button" onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => onStart(selected)}
            disabled={busy || !selected}
          >
            {busy ? <IconSpinner className="btn-icon" /> : <IconDownload className="btn-icon" />}
            开始下载
          </button>
        </div>
      </div>
    </div>
  )
}

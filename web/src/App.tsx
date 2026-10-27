import { useEffect, useRef, useState } from 'react'

import { api, ApiError } from './lib/api'
import type { Task, TaskStatus } from './lib/types'
import { useSnapshot } from './lib/useSnapshot'
import { Composer } from './components/Composer'
import { QualityPanel } from './components/QualityPanel'
import { TaskProgress } from './components/TaskProgress'
import { CompletedCard, FailedCard } from './components/TaskResult'
import { TopBar } from './components/TopBar'
import { IconAlert } from './components/icons'

const ACTIVE_STATUSES: readonly TaskStatus[] = [
  'resolve_queued',
  'resolving',
  'download_queued',
  'downloading',
  'merging',
]
const TERMINAL_STATUSES: readonly TaskStatus[] = ['completed', 'failed', 'cancelled', 'interrupted']

const isActive = (task: Task) => ACTIVE_STATUSES.includes(task.status)
const isTerminal = (task: Task) => TERMINAL_STATUSES.includes(task.status)

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '操作失败，请稍后重试'
}

const HOW_TO = [
  { title: '粘贴链接', detail: 'B站、抖音、YouTube 及常见短链接，抖音可直接粘贴分享文案' },
  { title: '解析并选清晰度', detail: '默认「最佳可用画质」，也可以手动挑一档' },
  { title: '排队下载并保存', detail: '服务端按平台限频排队，完成后点「保存到设备」' },
]

export default function App() {
  const { snapshot, connected, loadError, refresh } = useSnapshot()
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [showAllResults, setShowAllResults] = useState(false)
  const lastStatus = useRef(new Map<string, TaskStatus>())

  const tasks = snapshot?.tasks ?? []
  const selection = tasks.filter((task) => task.status === 'awaiting_selection')
  const active = tasks.filter(isActive)
  // 只留最近一条结束任务作为「保存到设备 / 重试」入口，更早的折叠起来
  const terminal = tasks.filter(isTerminal)
  const results = showAllResults ? terminal : terminal.slice(0, 1)
  const olderCount = Math.max(terminal.length - 1, 0)

  useEffect(() => {
    const seen = lastStatus.current
    const messages: string[] = []
    for (const task of tasks) {
      const previous = seen.get(task.id)
      if (previous !== task.status) {
        seen.set(task.id, task.status)
        if (previous !== undefined) {
          messages.push(`${task.title ?? '任务'}：${task.status_label}`)
        }
      }
    }
    for (const key of [...seen.keys()]) {
      if (!tasks.some((task) => task.id === key)) seen.delete(key)
    }
    if (messages.length > 0) setAnnouncement(messages.join('；'))
  }, [tasks])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setFormError(null)
    try {
      await action()
      await refresh()
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const handleResolve = (text: string) => {
    void run(async () => {
      await api.createTask(text)
    })
  }

  return (
    <div className={`page ${tasks.length > 0 ? 'page--app' : ''}`}>
      <TopBar proxy={snapshot?.proxy ?? null} connected={connected} />

      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      <main>
        {tasks.length === 0 ? (
          <section className="hero" aria-labelledby="hero-title">
            <h1 className="hero-title" id="hero-title">
              把视频<span className="hero-accent">留在本地</span>，
              <br />
              不用再找第三方站点。
            </h1>
            <p className="hero-lead">粘贴链接，解析清晰度，服务端排队下载，进度实时回传。</p>
          </section>
        ) : null}

        {loadError && !snapshot ? (
          <div className="banner banner-error banner-standalone" role="alert">
            <IconAlert className="banner-icon" />
            <p className="banner-text">{loadError}</p>
          </div>
        ) : null}

        <section className="block" aria-label="粘贴链接">
          <div className="surface">
            <Composer busy={busy} error={formError} onSubmit={handleResolve} />
          </div>
        </section>

        {selection.map((task) => (
          <section className="block" key={task.id} aria-label="选择清晰度">
            <QualityPanel
              task={task}
              busy={busy}
              onStart={(optionId) => void run(() => api.startDownload(task.id, optionId))}
              onCancel={() => void run(() => api.cancel(task.id))}
            />
          </section>
        ))}

        {active.map((task) => (
          <section className="block" key={task.id} aria-label="下载进度">
            <TaskProgress
              task={task}
              busy={busy}
              onCancel={() => void run(() => api.cancel(task.id))}
            />
          </section>
        ))}

        {results.length > 0 ? (
          <section className="block" aria-labelledby="block-results">
            <div className="block-head">
              <h2 className="block-kicker" id="block-results">
                最近任务
              </h2>
              {olderCount > 0 ? (
                <button
                  type="button"
                  className="link-btn"
                  aria-expanded={showAllResults}
                  aria-controls="results-list"
                  onClick={() => setShowAllResults((value) => !value)}
                >
                  {showAllResults ? '收起更早的任务' : `查看全部 ${terminal.length} 条`}
                </button>
              ) : null}
            </div>
            <div className="result-grid" id="results-list">
              {results.map((task) =>
                task.status === 'completed' ? (
                  <CompletedCard
                    key={task.id}
                    task={task}
                    ttlHours={snapshot?.limits.file_ttl_hours ?? 24}
                  />
                ) : (
                  <FailedCard
                    key={task.id}
                    task={task}
                    busy={busy}
                    onRetry={() => void run(() => api.retry(task.id))}
                  />
                ),
              )}
            </div>
          </section>
        ) : null}

        {tasks.length === 0 ? (
          <section className="block" aria-label="使用方式">
            <ol className="howto">
              {HOW_TO.map((item, index) => (
                <li className="howto-item" key={item.title}>
                  <span className="howto-num" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span className="howto-body">
                    <b className="howto-title">{item.title}</b>
                    <span className="howto-detail">{item.detail}</span>
                  </span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </main>

      <footer className="page-foot">
        <p className="page-foot-brand">SnapDown Anything · payson</p>
      </footer>
    </div>
  )
}

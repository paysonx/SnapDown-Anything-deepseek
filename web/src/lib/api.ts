import type { ApiErrorBody, Snapshot, Task } from './types'

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code = 'ERROR', status = 0) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError('无法连接本地服务，请确认后端已启动', 'NETWORK')
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      body = null
    }
    const message = body?.error?.message || `请求失败（HTTP ${response.status}）`
    const code = body?.error?.code || 'HTTP_ERROR'
    throw new ApiError(message, code, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const json = (payload: unknown): RequestInit => ({
  method: 'POST',
  body: JSON.stringify(payload),
})

export const api = {
  createTask(text: string): Promise<{ task: Task }> {
    return request('/api/tasks', json({ text }))
  },
  listTasks(): Promise<Snapshot> {
    return request('/api/tasks')
  },
  startDownload(taskId: string, optionId: string): Promise<{ task: Task }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/download`, json({ option_id: optionId }))
  },
  cancel(taskId: string): Promise<{ task: Task }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
  },
  retry(taskId: string): Promise<{ task: Task }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: 'POST' })
  },
  fileUrl(taskId: string): string {
    return `/api/tasks/${encodeURIComponent(taskId)}/file`
  },
}

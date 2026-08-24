import axios from 'axios'
import type { TripFormData, TripPlanResponse, HistoryItem, HistoryListData } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  /*timeout: 120000,*/
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log('Request:', config.method?.toUpperCase(), config.url)
    // 登录后自动附带 JWT，供后端鉴权与用户记忆绑定使用
    const token = localStorage.getItem('tripToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('Response error:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

/**
 * 通过 SSE 流式生成旅行计划。
 * 返回 AbortController，调用方可据此取消请求。
 */
export function generateTripPlanSSE(
  formData: TripFormData,
  onStep: (label: string, node?: string, status?: string) => void,
  onToolStep: (node: string, label: string, index: number) => void,
  onResult: (data: any) => void,
  onError: (error: string) => void,
): AbortController {
  const controller = new AbortController()

  // SSE 请求同样携带 JWT，登录用户才能持久化偏好记忆
  const token = localStorage.getItem('tripToken')
  const sseHeaders: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) sseHeaders.Authorization = `Bearer ${token}`
  fetch(`${API_BASE_URL}/api/trip/plan`, {
    method: 'POST',
    headers: sseHeaders,
    body: JSON.stringify(formData),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // 刷新剩余缓冲区
          if (buffer.trim() && buffer.trim().startsWith('data: ')) {
            try {
              const data = JSON.parse(buffer.trim().slice(6))
              if (data.type === 'step') {
                onStep(data.label || `${data.node}: ${data.status}`, data.node, data.status)
              } else if (data.type === 'tool_step') {
                onToolStep(data.node, data.label, data.tool_index)
              } else if (data.type === 'result') {
                onResult(data.data)
              } else if (data.type === 'error') {
                onError(data.message)
              }
            } catch (e) { /* ignore */ }
          }
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          if (trimmed.startsWith('data: ')) {
            try {
              const data = JSON.parse(trimmed.slice(6))
              if (data.type === 'step') {
                onStep(data.label || `${data.node}: ${data.status}`, data.node, data.status)
              } else if (data.type === 'tool_step') {
                onToolStep(data.node, data.label, data.tool_index)
              } else if (data.type === 'result') {
                onResult(data.data)
              } else if (data.type === 'error') {
                onError(data.message)
              }
            } catch (e) { /* ignore */ }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message || 'Request failed')
      }
    })

  return controller
}

/**
 * 提交行程规划后台任务：立即返回 task_id，前端轮询状态（方案B异步化）。
 * 幂等：可传 idempotencyKey，相同 key 复用已有任务避免重复生成。
 */
export async function submitTripPlanTask(
  formData: TripFormData,
  idempotencyKey?: string,
): Promise<{ task_id: string; reused?: boolean }> {
  try {
    const response = await apiClient.post('/api/trip/plan/task', formData, {
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
    })
    return response.data
  } catch (error: any) {
    console.error('Submit trip plan task failed:', error)
    throw new Error(error.response?.data?.detail || error.response?.data?.message || error.message || 'Failed to submit plan task')
  }
}

/**
 * 轮询查询行程规划任务状态。
 * 返回任务快照；失败时抛错（如任务不存在/过期）。
 */
export async function fetchTripPlanTask(taskId: string): Promise<any> {
  try {
    const response = await apiClient.get(`/api/trip/plan/task/${taskId}`)
    return response.data
  } catch (error: any) {
    console.error('Fetch trip plan task failed:', error)
    throw new Error(error.response?.data?.detail || error.response?.data?.message || error.message || 'Failed to fetch plan task')
  }
}

/**
 * 同步生成旅行计划（备用方案）。
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan/sync', formData)
    return response.data
  } catch (error: any) {
    console.error('Generate trip plan failed:', error)
    throw new Error(error.response?.data?.detail || error.message || 'Failed to generate plan')
  }
}

/**
 * 与伴游 Agent 进行流式聊天。
 */
export function chatWithCompanionSSE(
  message: string,
  plan: any,
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (error: string) => void,
): AbortController {
  const controller = new AbortController()

  fetch(`${API_BASE_URL}/api/trip/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, plan }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // 刷新剩余缓冲区
          if (buffer.trim() && buffer.trim().startsWith('data: ')) {
            try {
              const data = JSON.parse(buffer.trim().slice(6))
              if (data.type === 'chunk') {
                onChunk(data.content)
              } else if (data.type === 'done') {
                onDone()
              }
            } catch (e) { /* ignore */ }
          }
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue

          try {
            const data = JSON.parse(trimmed.slice(6))
            if (data.type === 'chunk') {
              onChunk(data.content)
            } else if (data.type === 'done') {
              onDone()
            }
          } catch (e) { /* ignore */ }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message || 'Chat failed')
      }
    })

  return controller
}

/**
 * 健康检查。
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('Health check failed:', error)
    throw new Error(error.message || 'Health check failed')
  }
}

/** ============ 历史会话记录 API ============ */

/** 分页查询历史记录（每页最多10条） */
export async function fetchHistoryList(page: number = 1, pageSize: number = 10): Promise<HistoryListData> {
  try {
    const response = await apiClient.get('/api/history', { params: { page, page_size: pageSize } })
    return response.data?.data || { items: [], total: 0, page, page_size: pageSize }
  } catch (error: any) {
    console.error('Fetch history list failed:', error)
    return { items: [], total: 0, page, page_size: pageSize }
  }
}

/** 查询单条历史记录详情 */
export async function fetchHistoryDetail(historyId: number): Promise<HistoryItem | null> {
  try {
    const response = await apiClient.get(`/api/history/${historyId}`)
    return response.data?.data || null
  } catch (error: any) {
    console.error('Fetch history detail failed:', error)
    return null
  }
}

/** 保存一条历史记录（生成方案后自动调用） */
export async function saveHistory(payload: {
  title?: string
  request_data: Record<string, any>
  plans: any[]
  active_plan_type: string
}): Promise<HistoryItem | null> {
  try {
    const response = await apiClient.post('/api/history', payload)
    return response.data?.data || null
  } catch (error: any) {
    console.error('Save history failed:', error)
    return null
  }
}

/** 更新历史记录标题/方案 */
export async function updateHistory(
  historyId: number,
  payload: { title?: string; request_data?: Record<string, any>; plans?: any[]; active_plan_type?: string },
): Promise<HistoryItem | null> {
  try {
    const response = await apiClient.put(`/api/history/${historyId}`, payload)
    return response.data?.data || null
  } catch (error: any) {
    console.error('Update history failed:', error)
    return null
  }
}

/** 删除历史记录 */
export async function deleteHistory(historyId: number): Promise<boolean> {
  try {
    const response = await apiClient.delete(`/api/history/${historyId}`)
    return response.data?.success === true
  } catch (error: any) {
    console.error('Delete history failed:', error)
    return false
  }
}

/** ============ 登录鉴权 API ============ */

/** 注册，成功返回 { token, username, user_id } */
export async function register(username: string, password: string): Promise<{ token: string; username: string; user_id: number }> {
  const response = await apiClient.post('/api/auth/register', { username, password })
  return response.data?.data
}

/** 登录，成功返回 { token, username, user_id } */
export async function login(username: string, password: string): Promise<{ token: string; username: string; user_id: number }> {
  const response = await apiClient.post('/api/auth/login', { username, password })
  return response.data?.data
}

export default apiClient

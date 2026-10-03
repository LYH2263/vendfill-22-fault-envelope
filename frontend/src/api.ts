// 失败信封：且仅且 error_code / object_id / message 三字段。
// 前端不造码、不补全说明，只逐字渲染。
export interface FailureEnvelope {
  error_code: string
  object_id: string
  message: string
  drifted?: boolean
}

export class EnvelopeError extends Error {
  readonly error_code: string
  readonly object_id: string
  readonly drifted: boolean
  constructor(env: FailureEnvelope) {
    super(env.message)
    this.name = 'EnvelopeError'
    this.error_code = env.error_code
    this.object_id = env.object_id
    this.drifted = env.drifted === true
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  const text = await res.text()
  let body: any = null
  if (text) {
    try { body = JSON.parse(text) } catch { body = null }
  }
  if (!res.ok) {
    // 只认三字段信封；万一服务端给了别的形状，也包成信封，绝不向上抛无码串
    if (body && typeof body.error_code === 'string'
        && typeof body.object_id === 'string' && typeof body.message === 'string') {
      throw new EnvelopeError(body as FailureEnvelope)
    }
    throw new EnvelopeError({
      error_code: 'BAD_RESPONSE',
      object_id: path,
      message: text || res.statusText || '请求失败，且未收到三字段错误信封',
    })
  }
  if (res.status === 204) return undefined as T
  return body as T
}

import { isEnvelope, NETWORK_ERROR, type FailEnvelope } from './errors'

// 所有失败都归一为带三字段信封的错误；成功路径绝不抛它、也绝不携带这三个字段。
export class ApiFailError extends Error {
  env: FailEnvelope
  status: number
  constructor(env: FailEnvelope, status: number) {
    super(`${env.code}: ${env.subject}`)
    this.name = 'ApiFailError'
    this.env = env
    this.status = status
  }
}

function asEnvelope(body: unknown, status: number, fallbackSubject: string): FailEnvelope {
  // 服务端必须回三字段信封；万一拿到非信封体，也在客户端补成有码信封，
  // 保证页面永远不会只显示无码字符串。
  if (isEnvelope(body)) return body
  return {
    code: status >= 500 ? 'internal_error' : 'bad_request',
    subject: fallbackSubject,
    detail:
      typeof body === 'string' && body
        ? body
        : `请求失败（HTTP ${status}）`,
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch('/api' + path, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      ...init,
    })
  } catch {
    // 断网等本地失败同样给三字段信封，杜绝无码串。
    throw new ApiFailError(
      {
        code: NETWORK_ERROR,
        subject: `${init?.method || 'GET'} ${path}`,
        detail: '网络不可用：请求未到达服务端，本次操作未落任何改动，请检查网络后重试。',
      },
      0,
    )
  }

  const text = await res.text()
  if (!res.ok) {
    let body: unknown = null
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      body = text
    }
    throw new ApiFailError(asEnvelope(body, res.status, `${init?.method || 'GET'} ${path}`), res.status)
  }
  if (res.status === 204 || !text) return undefined as T
  return JSON.parse(text) as T
}

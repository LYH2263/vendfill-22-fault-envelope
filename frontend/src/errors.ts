// 说明全文真源的只读镜像，唯一真源在后端 app/services/errors.py 的 DETAIL_FULL。
// 后端 pytest 会逐字比对两边模板，禁止只改一处。
// 前端只用它做「说明漂移」比对：接口给的 detail 若是截短串，与全文不一致即标漂移；
// 禁止用全文补全、改写或回写 detail。

export interface FailEnvelope {
  code: string
  subject: string
  detail: string
}

export const CANONICAL_DETAIL: Record<string, string> = {
  generation_rejected:
    '生成被拒：{subject} 存在缺口为负的超占货道，库存与在途之和已超过货道容量，无法生成补货单；请先核销在途或调整库存后重试。',
  manual_over_gap:
    '手改超缺口：{subject} 的手工补量超过该货道当前缺口，补量必须为不超过缺口的非负整数；请按缺口范围内重新填报。',
  fulfill_conflict:
    '核销冲突：{subject} 核销时库存或在途已相对生成补货单时发生变化，为避免半改库存，本次核销已整体作废、不落任何改动；请重新生成补货单。',
  invalid_capacity:
    '非法容量保存：{subject} 提交的容量非法，容量必须为不小于 1 的整数，且不得低于当前库存与在途之和；本次保存已拒绝。',
  location_not_found: '点位不存在：{subject} 未找到，请核对点位标识后重试。',
  lane_not_found: '货道不存在：{subject} 未找到，请核对货道标识后重试。',
  refill_not_found: '补货单不存在：{subject} 未找到，请核对补货单号后重试。',
  bad_request: '请求不合法：{subject}；请按接口字段与类型要求修正后重试。',
  not_found: '资源不存在：{subject} 未匹配到任何接口或数据，请核对地址后重试。',
  method_not_allowed: '方法不允许：{subject}；请改用该资源支持的请求方法。',
  internal_error: '服务内部错误：{subject} 处理失败，本次请求未落任何改动，请稍后重试。',
}

// 仅本地网络层使用（后端不会下发），仍保持三字段形状，杜绝无码字符串。
export const NETWORK_ERROR = 'network_error'

export function fullDetail(code: string, subject: string): string | null {
  const tpl = CANONICAL_DETAIL[code]
  if (!tpl) return null
  return tpl.replace(/\{subject\}/g, subject)
}

// 回包 detail 与全文不一致即说明被截短（漂移）。只报告，绝不补全。
export function isDrift(env: FailEnvelope): boolean {
  const full = fullDetail(env.code, env.subject)
  return full !== null && full !== env.detail
}

export function isEnvelope(x: unknown): x is FailEnvelope {
  if (!x || typeof x !== 'object') return false
  const o = x as Record<string, unknown>
  return typeof o.code === 'string' &&
    typeof o.subject === 'string' &&
    typeof o.detail === 'string'
}

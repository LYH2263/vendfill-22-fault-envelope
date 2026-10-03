import { ref } from 'vue'
import { api, ApiFailError } from '../api'
import type { FailEnvelope } from '../errors'

// 各页共用同一份失败来源：
// - 页面挂载时读服务端落库的最近失败（保证重开页面仍是同一套三字段）；
// - 动作当场失败时直接用本次回包信封（它与刚落库的流水逐字段同一份）。
export function useFailure(locationId = 1) {
  const error = ref<FailEnvelope | null>(null)

  async function loadFailure() {
    try {
      error.value = await api<FailEnvelope | null>(
        `/refills/last-failure?location_id=${locationId}`,
      )
    } catch {
      error.value = null
    }
  }

  // 失败只照显回包三字段；服务端已把同一份落库，重开页面 loadFailure 取回的仍一致。
  function reportFailed(e: unknown) {
    if (e instanceof ApiFailError) error.value = e.env
  }

  function clear() {
    error.value = null
  }

  return { error, loadFailure, reportFailed, clear }
}

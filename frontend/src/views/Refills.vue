<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, EnvelopeError, type FailureEnvelope } from '../api'
import ErrorBar from '../components/ErrorBar.vue'

const data = ref<any>(null)
const failure = ref<FailureEnvelope | null>(null)
// 手改输入只在本地暂存；只有后端成功回包才会写回单据
const drafts = ref<Record<number, string>>({})
const busy = ref<string>('')

function syncDrafts() {
  const d: Record<number, string> = {}
  for (const l of data.value?.lines ?? []) d[l.lane_id] = String(l.fill_qty)
  drafts.value = d
}

async function loadFailure() {
  // 全局最近一条失败：与货道页错误条同源，保证三口同字
  const r = await api<{ failure: FailureEnvelope | null }>('/failures/latest?location_id=1')
  failure.value = r.failure
}

async function loadOrder() {
  data.value = await api('/refills/latest?location_id=1')
  syncDrafts()
}

function envOf(e: unknown): FailureEnvelope | null {
  return e instanceof EnvelopeError
    ? { error_code: e.error_code, object_id: e.object_id, message: e.message }
    : null
}

onMounted(async () => {
  try { await loadOrder() } catch (e) {
    const env = envOf(e); if (env) failure.value = env
  }
  await loadFailure()
})

// 成功才更新单据并撤下错误条；失败只上错误条，单据与库存维持失败前状态
async function run() {
  busy.value = 'run'
  try {
    data.value = await api('/refills/run?location_id=1', { method: 'POST' })
    syncDrafts(); failure.value = null
  } catch (e) {
    const env = envOf(e); if (env) { failure.value = env; await loadFailure() }
  } finally { busy.value = '' }
}

async function saveManual() {
  if (!data.value) return
  busy.value = 'edit'
  const lines = Object.entries(drafts.value).map(([lane_id, raw]) => ({
    lane_id: Number(lane_id),
    // 非整数原样送后端，由后端按原因码拒绝；前端不替后端造结果
    fill_qty: /^\d+$/.test(raw.trim()) ? Number(raw) : raw,
  }))
  try {
    data.value = await api(`/refills/orders/${data.value.id}/manual-edit`, {
      method: 'POST', body: JSON.stringify({ lines }),
    })
    syncDrafts(); failure.value = null
  } catch (e) {
    const env = envOf(e); if (env) { failure.value = env; await loadFailure(); syncDrafts() }
  } finally { busy.value = '' }
}

async function redeem() {
  if (!data.value) return
  busy.value = 'redeem'
  try {
    data.value = await api(`/refills/orders/${data.value.id}/redeem`, { method: 'POST' })
    failure.value = null
  } catch (e) {
    const env = envOf(e); if (env) { failure.value = env; await loadFailure() }
  } finally { busy.value = '' }
}

function statusText(s: string) {
  return s === 'need_fill' ? '待补' : s === 'full' ? '满仓' : '超占'
}
</script>

<template>
  <h1>补货小票</h1>
  <p class="sub">gap = 容量 − 库存 − 在途 · 成功与失败互斥 · 收据纸样式</p>

  <!-- 失败路径：只渲染三字段信封，绝不把成功画成失败条 -->
  <ErrorBar :failure="failure" />

  <div class="vf-actions">
    <button class="btn" :disabled="!!busy" @click="run">
      {{ busy === 'run' ? '生成中…' : '生成补货单' }}
    </button>
    <button class="btn btn-secondary" :disabled="!!busy || !data || !!data?.redeemed_at" @click="saveManual">
      保存手改
    </button>
    <button class="btn btn-secondary" :disabled="!!busy || !data || !!data?.redeemed_at" @click="redeem">
      核销落库
    </button>
    <span v-if="data?.redeemed_at" class="badge badge-ok">已核销 {{ data.redeemed_at }}</span>
  </div>

  <div style="margin-top:1rem" v-if="data">
    <div class="vf-receipt">
      <h2>*** VendFill 补货单 #{{ data.id }} ***</h2>
      <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
        <span>货道 / 商品</span><span>补量</span>
      </div>
      <div class="vf-receipt-line" v-for="l in data.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}
          <small>({{ statusText(l.status) }}) · 缺{{ l.gap }}</small>
        </span>
        <span>
          <input
            class="vf-edit-input"
            type="text"
            inputmode="numeric"
            :value="drafts[l.lane_id]"
            :disabled="!!data.redeemed_at"
            @input="drafts[l.lane_id] = ($event.target as HTMLInputElement).value"
          />
        </span>
      </div>
      <p style="text-align:center;margin:1rem 0 0;font-size:0.72rem;color:#6a5e48">
        谢谢使用 · 请核对后装机
      </p>
    </div>
  </div>
</template>

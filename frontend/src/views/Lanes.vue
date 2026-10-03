<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, EnvelopeError, type FailureEnvelope } from '../api'
import ErrorBar from '../components/ErrorBar.vue'

const rows = ref<any[]>([])
const refill = ref<any>(null)
const failure = ref<FailureEnvelope | null>(null)
const capDrafts = ref<Record<number, string>>({})
const busyId = ref<number | null>(null)

function envOf(e: unknown): FailureEnvelope | null {
  return e instanceof EnvelopeError
    ? { error_code: e.error_code, object_id: e.object_id, message: e.message }
    : null
}

async function loadFailure() {
  // 全局最近一条失败：与补货单页错误条同源，保证三口同字
  const r = await api<{ failure: FailureEnvelope | null }>('/failures/latest?location_id=1')
  failure.value = r.failure
}

async function loadRows() {
  rows.value = await api('/lanes?location_id=1')
  const d: Record<number, string> = {}
  for (const r of rows.value) d[r.id] = String(r.capacity)
  capDrafts.value = d
}

async function saveCap(id: number) {
  busyId.value = id
  const raw = capDrafts.value[id]
  // 非法值原样送后端：必须由后端回原因码信封，前端不代造失败
  const cap = /^\d+$/.test(raw.trim()) ? Number(raw) : raw
  try {
    const lane = await api(`/lanes/${id}/capacity`, {
      method: 'PATCH', body: JSON.stringify({ capacity: cap }),
    })
    const i = rows.value.findIndex(r => r.id === id)
    if (i >= 0) rows.value[i] = lane
    capDrafts.value[id] = String(lane.capacity)
    failure.value = null
  } catch (e) {
    const env = envOf(e)
    if (env) { failure.value = env; await loadFailure() }
  } finally { busyId.value = null }
}

onMounted(async () => {
  try {
    await loadRows()
  } catch (e) {
    const env = envOf(e); if (env) failure.value = env
  }
  // 只读取最近一张补货单做机面预览，绝不在此触发生成（生成失败必须走信封）
  try { refill.value = await api('/refills/latest?location_id=1') }
  catch (e) { const env = envOf(e); if (env) failure.value = env }
  await loadFailure()
})
</script>

<template>
  <h1>货道格子</h1>
  <p class="sub">机面货道网格 · 格内库存条 · 右侧补货小票 · 容量保存失败走同一套信封</p>

  <ErrorBar :failure="failure" />

  <div class="vf-machine-layout">
    <div class="vf-slot-grid">
      <div v-for="r in rows" :key="r.id" class="vf-slot">
        <div class="vf-slot-no">{{ r.slot_no }}</div>
        <div class="vf-slot-sku">{{ r.sku_name }}</div>
        <div class="vf-slot-bar">
          <div
            class="vf-slot-fill"
            :class="{ 'vf-need': r.gap > 0, 'vf-over': r.gap < 0 }"
            :style="{ width: Math.min(r.fill_pct, 100) + '%' }"
          />
        </div>
        <div class="vf-slot-meta">{{ r.stock }}/{{ r.capacity }} · 缺 {{ r.gap }}</div>
        <div class="vf-slot-cap">
          <input
            class="vf-edit-input"
            type="text"
            inputmode="numeric"
            :value="capDrafts[r.id]"
            @input="capDrafts[r.id] = ($event.target as HTMLInputElement).value"
          />
          <button class="btn vf-cap-btn" :disabled="busyId === r.id" @click="saveCap(r.id)">
            {{ busyId === r.id ? '…' : '存容量' }}
          </button>
        </div>
      </div>
    </div>
    <aside class="vf-receipt" v-if="refill">
      <h2>*** 补货建议单 #{{ refill.id }} ***</h2>
      <div class="vf-receipt-line" v-for="l in refill.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}</span>
        <span>x{{ l.fill_qty }}</span>
      </div>
      <p class="muted" style="margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48;text-align:center">
        — 机面打印预览 —
      </p>
    </aside>
  </div>
</template>

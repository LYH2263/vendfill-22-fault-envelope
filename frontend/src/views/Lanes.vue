<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import ErrorBar from '../components/ErrorBar.vue'
import { useFailure } from '../composables/useFailure'

const LOC = 1
const { error, loadFailure, reportFailed, clear } = useFailure(LOC)
const rows = ref<any[]>([])
const refill = ref<any>(null)
const capDraft = ref<Record<number, string>>({})
const busy = ref(false)

async function loadRows() {
  rows.value = await api('/lanes')
  const d: Record<number, string> = {}
  rows.value.forEach((r) => { d[r.id] = String(r.capacity) })
  capDraft.value = d
}

async function loadSuggestion() {
  // 只读取最近一张草稿做机面预览，绝不自动补单。
  try {
    refill.value = await api(`/refills/latest?location_id=${LOC}`)
  } catch {
    refill.value = null
  }
}

async function rerun() {
  busy.value = true
  try {
    refill.value = await api(`/refills/run?location_id=${LOC}`, { method: 'POST' })
    await loadRows()
    clear()
  } catch (e) {
    refill.value = null
    reportFailed(e) // 生成被拒等：三字段信封进错误条
  } finally {
    busy.value = false
  }
}

async function saveCap(r: any) {
  busy.value = true
  const value = Number(capDraft.value[r.id])
  try {
    await api(`/lanes/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify({ capacity: value }),
    })
    await loadRows()
    clear()
  } catch (e) {
    reportFailed(e) // 非法容量保存：三字段信封进错误条
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadFailure(), loadRows(), loadSuggestion()])
})
</script>
<template>
  <h1>货道格子</h1>
  <p class="sub">机面货道网格 · 格内库存条 · 右侧补货小票</p>
  <ErrorBar :env="error" />
  <div class="vf-actions" style="margin-bottom:0.75rem">
    <button class="btn-mini" :disabled="busy" @click="rerun">重新生成建议</button>
  </div>
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
        <div class="vf-editrow" style="margin-top:0.3rem">
          <input v-model="capDraft[r.id]" type="number" min="1" inputmode="numeric" title="容量" />
          <button class="btn-mini" :disabled="busy" @click="saveCap(r)">存容量</button>
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
        — 机面打印预览 · {{ refill.status === 'fulfilled' ? '已核销' : '待核销' }} —
      </p>
    </aside>
  </div>
</template>

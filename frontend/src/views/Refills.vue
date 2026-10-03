<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import ErrorBar from '../components/ErrorBar.vue'
import { useFailure } from '../composables/useFailure'

const LOC = 1
const { error, loadFailure, reportFailed, clear } = useFailure(LOC)
const order = ref<any>(null)
const drafts = ref<Record<number, string>>({})
const busy = ref(false)
const successMsg = ref('')

function syncDrafts() {
  const d: Record<number, string> = {}
  order.value?.lines.forEach((l: any) => { d[l.lane_id] = String(l.fill_qty) })
  drafts.value = d
}

async function loadOrder() {
  try {
    order.value = await api(`/refills/latest?location_id=${LOC}`)
  } catch {
    order.value = null
  }
  syncDrafts()
}

async function run() {
  busy.value = true
  successMsg.value = ''
  try {
    // 成功：回包只有补货单字段，不含原因码，也不画失败条。
    order.value = await api(`/refills/run?location_id=${LOC}`, { method: 'POST' })
    syncDrafts()
    clear()
  } catch (e) {
    // 失败：只照显回包三字段信封（服务端已落同一套，重开仍一致）。
    reportFailed(e)
  } finally {
    busy.value = false
  }
}

async function saveManual() {
  if (!order.value) return
  busy.value = true
  successMsg.value = ''
  const fills: Record<string, number> = {}
  for (const l of order.value.lines) {
    if (l.status !== 'need_fill') continue
    const raw = drafts.value[l.lane_id]
    const qty = raw === undefined || raw === '' ? 0 : Number(raw)
    fills[l.lane_id] = qty
  }
  try {
    order.value = await api(`/refills/${order.value.id}/adjust`, {
      method: 'POST',
      body: JSON.stringify({ fills }),
    })
    syncDrafts()
    clear()
    successMsg.value = '手改已落单：补量未超缺口，补货单已更新。'
  } catch (e) {
    reportFailed(e)
  } finally {
    busy.value = false
  }
}

async function fulfill() {
  if (!order.value) return
  busy.value = true
  successMsg.value = ''
  try {
    order.value = await api(`/refills/${order.value.id}/fulfill`, { method: 'POST' })
    clear()
    successMsg.value = '核销成功：库存已按补货量更新。'
  } catch (e) {
    reportFailed(e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadFailure(), loadOrder()])
})
</script>
<template>
  <h1>补货小票</h1>
  <p class="sub">gap = 容量 − 库存 − 在途 · 收据纸样式</p>
  <ErrorBar :env="error" />
  <div class="vf-okline" v-if="successMsg">✓ {{ successMsg }}</div>
  <div class="vf-actions">
    <button class="btn" :disabled="busy" @click="run">生成补货单</button>
    <button class="btn-mini" :disabled="busy || !order || order.status === 'fulfilled'" @click="saveManual">
      保存手改
    </button>
    <button class="btn-mini" :disabled="busy || !order || order.status === 'fulfilled'" @click="fulfill">
      核销落库
    </button>
    <span v-if="order" class="vf-order-state">
      单号 #{{ order.id }} ·
      <span :class="order.status === 'fulfilled' ? 'vf-fulfilled' : 'muted'">
        {{ order.status === 'fulfilled' ? '已核销' : '待核销' }}
      </span>
    </span>
  </div>
  <div style="margin-top:1rem" v-if="order">
    <div class="vf-receipt">
      <h2>*** VendFill 补货单 ***</h2>
      <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
        <span>货道 / 商品</span><span>补量</span>
      </div>
      <div class="vf-receipt-line" v-for="l in order.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}
          <small>({{ l.status === 'need_fill' ? '待补' : l.status === 'full' ? '满仓' : '超占' }})</small>
        </span>
        <span class="vf-editrow" v-if="l.status === 'need_fill' && order.status !== 'fulfilled'">
          <input
            v-model="drafts[l.lane_id]"
            type="number" min="0" :max="l.gap" inputmode="numeric"
          /> / 缺{{ l.gap }}
        </span>
        <span v-else>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
      </div>
      <p style="text-align:center;margin:1rem 0 0;font-size:0.72rem;color:#6a5e48">谢谢使用 · 请核对后装机</p>
    </div>
  </div>
  <p class="muted" v-else style="margin-top:1rem;font-size:0.8rem">暂无补货单，请先生成。</p>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, EnvelopeError, type FailureEnvelope } from '../api'
import ErrorBar from '../components/ErrorBar.vue'
const lanes = ref<any[]>([])
const failure = ref<FailureEnvelope | null>(null)
onMounted(async () => {
  try {
    lanes.value = (await api('/refills/full?location_id=1')).lanes
  } catch (e) {
    if (e instanceof EnvelopeError)
      failure.value = { error_code: e.error_code, object_id: e.object_id, message: e.message }
  }
})
</script>
<template>
  <h1>满仓</h1>
  <p class="sub">缺口为 0 的货道（无需补货）</p>
  <ErrorBar :failure="failure" />
  <div class="card" v-if="!failure">
    <table>
      <thead><tr><th>货道</th><th>商品</th><th>库存</th><th>在途</th><th>容量</th></tr></thead>
      <tbody>
        <tr v-for="l in lanes" :key="l.lane_id">
          <td>{{ l.slot_no }}</td><td>{{ l.sku_name }}</td><td>{{ l.stock }}</td><td>{{ l.in_transit }}</td><td>{{ l.capacity }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, EnvelopeError, type FailureEnvelope } from '../api'
import ErrorBar from '../components/ErrorBar.vue'
const s = ref<any>({})
const failure = ref<FailureEnvelope | null>(null)
onMounted(async () => {
  try {
    s.value = await api('/refills/summary?location_id=1')
  } catch (e) {
    if (e instanceof EnvelopeError)
      failure.value = { error_code: e.error_code, object_id: e.object_id, message: e.message }
  }
})
</script>
<template>
  <h1>汇总</h1>
  <p class="sub">本点位补货建议合计</p>
  <ErrorBar :failure="failure" />
  <div class="card grid" v-if="!failure" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">建议补货总量</div><div class="stat">{{ s.total_fill }}</div></div>
    <div><div class="muted">待补货道</div><div class="stat">{{ s.need_fill_count }}</div></div>
    <div><div class="muted">满仓货道</div><div class="stat">{{ s.full_count }}</div></div>
    <div><div class="muted">超占货道</div><div class="stat">{{ s.overbooked_count }}</div></div>
  </div>
</template>

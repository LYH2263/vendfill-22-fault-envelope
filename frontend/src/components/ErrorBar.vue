<script setup lang="ts">
import { computed } from 'vue'
import { isDrift, type FailEnvelope } from '../errors'

// 失败条只渲染信封三字段，逐字段照抄：原因码 / 对象标识 / 说明。
// detail 永远照显服务端给的串（可能已截短）；与全文不一致时只标「说明漂移」，
// 不在前端补全、不改写、不回写。
const props = defineProps<{ env: FailEnvelope | null }>()
const drift = computed(() => (props.env ? isDrift(props.env) : false))
</script>
<template>
  <div v-if="env" class="vf-errorbar" role="alert">
    <div class="vf-errorbar-head">
      <span class="vf-errorbar-title">⛔ 操作失败</span>
      <span class="vf-errorbar-code">{{ env.code }}</span>
    </div>
    <div class="vf-errorbar-row">
      <span class="vf-errorbar-lbl">对象标识</span>
      <span class="vf-errorbar-val">{{ env.subject }}</span>
    </div>
    <div class="vf-errorbar-row">
      <span class="vf-errorbar-lbl">说明</span>
      <span class="vf-errorbar-val">
        {{ env.detail }}<em v-if="drift" class="vf-drift-tag" title="说明相对全文真源已截短，仅照显不补全">说明漂移</em>
      </span>
    </div>
  </div>
</template>

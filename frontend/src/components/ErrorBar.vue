<script setup lang="ts">
import { computed } from 'vue'
import type { FailureEnvelope } from '../api'

// 两页唯一的失败条：接口回包 / 补货单页 / 货道页逐字段同一套渲染。
const props = defineProps<{ failure: FailureEnvelope | null }>()

// 漂移标记由说明全文自带（三字段信封里没有第四字段），
// 页上只识别、不补全、不写回。
const drifted = computed(() => !!props.failure && props.failure.message.endsWith('说明漂移'))
</script>

<template>
  <div v-if="failure" class="vf-error-bar" role="alert">
    <div class="vf-error-head">
      <span class="vf-error-title">补货失败</span>
      <span v-if="drifted" class="vf-drift-tag">说明漂移</span>
    </div>
    <dl class="vf-error-fields">
      <div><dt>原因码</dt><dd class="vf-error-code">{{ failure.error_code }}</dd></div>
      <div><dt>对象标识</dt><dd class="vf-error-obj">{{ failure.object_id }}</dd></div>
      <!-- 说明逐字显示：截短就显示截短文本，禁止前端补全 -->
      <div><dt>说明全文</dt><dd class="vf-error-msg">{{ failure.message }}</dd></div>
    </dl>
  </div>
</template>

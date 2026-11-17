<script setup lang="ts">
import { onMounted, ref } from "vue";

const agentStatus = ref("checking…");

onMounted(async () => {
  try {
    const r = await fetch("/api/health");
    agentStatus.value = r.ok ? "connected" : "unreachable";
  } catch {
    agentStatus.value = "unreachable";
  }
});
</script>

<template>
  <main class="shell">
    <h1>GUIBridge Dashboard</h1>
    <p class="status">desktop-agent: {{ agentStatus }}</p>
    <section class="placeholder">
      <h2>任务与状态迁移</h2>
      <p>S4 阶段实现：任务时间线、事件回放、截图证据、定位器修复记录、审批待办。</p>
    </section>
  </main>
</template>

<style>
.shell { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
.status { color: #666; }
.placeholder { border: 1px dashed #bbb; border-radius: 8px; padding: 1rem; margin-top: 1.5rem; }
</style>
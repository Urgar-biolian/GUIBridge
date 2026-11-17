<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ value: unknown; label?: string; collapsed?: boolean }>();

const pretty = computed(() => {
  try {
    return JSON.stringify(props.value, null, 2) ?? "null";
  } catch {
    return String(props.value);
  }
});
</script>

<template>
  <details class="json" :open="!collapsed">
    <summary>{{ label ?? "payload" }}</summary>
    <pre>{{ pretty }}</pre>
  </details>
</template>

<style scoped>
.json summary { cursor: pointer; color: var(--muted); font-size: 12px; }
.json pre {
  max-height: 320px;
  overflow: auto;
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

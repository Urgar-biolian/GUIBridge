<script setup lang="ts">
defineProps<{ state: string }>();

const LABELS: Record<string, string> = {
  submitted: "已提交",
  running: "运行中",
  claimed_done: "自称完成",
  verified: "已验证",
  failed: "失败",
  unknown: "未知",
  awaiting_approval: "等待审批",
};
</script>

<template>
  <!-- `claimed_done` is deliberately not styled like a success: docs/agent.md 状态语义 says it is not
       completion, and a green tick here would be the exact lie the verifier exists to prevent. -->
  <span class="tag" :class="`tag--${state}`">{{ LABELS[state] ?? state }}</span>
</template>

<style scoped>
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid currentColor;
  color: var(--muted);
  white-space: nowrap;
}
.tag--verified { color: var(--ok); }
.tag--running, .tag--submitted { color: var(--info); }
.tag--claimed_done { color: var(--warn); }
.tag--failed, .tag--unknown, .tag--awaiting_approval { color: var(--err); }
</style>

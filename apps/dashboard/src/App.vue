<script setup lang="ts">
import { computed, markRaw, onMounted, onUnmounted, ref } from "vue";
import { closeEvents, refresh, start, state } from "./state";
import ApprovalsView from "./views/ApprovalsView.vue";
import LocatorsView from "./views/LocatorsView.vue";
import ReplayView from "./views/ReplayView.vue";
import TasksView from "./views/TasksView.vue";

const TABS = [
  { id: "tasks", label: "任务与时间线", view: markRaw(TasksView) },
  { id: "replay", label: "事件回放", view: markRaw(ReplayView) },
  { id: "locators", label: "定位器与修复", view: markRaw(LocatorsView) },
  { id: "approvals", label: "审批与窗口", view: markRaw(ApprovalsView) },
] as const;

const active = ref<(typeof TABS)[number]["id"]>("tasks");
const current = computed(() => TABS.find((tab) => tab.id === active.value) ?? TABS[0]);
const simulated = computed(() => state.health?.channel.includes("simulated") ?? false);
const unreachable = computed(() => Boolean(state.errors.health) && !state.health);

onMounted(start);
onUnmounted(closeEvents);
</script>

<template>
  <main class="shell">
    <header class="bar">
      <div class="brand">
        <h1>GUIBridge Dashboard</h1>
        <p class="muted">本地控制平面 127.0.0.1:8765 · 只读展示 + 审批，不提供任何新的控制通道</p>
      </div>
      <div class="chips">
        <span class="chip" :class="state.stream === 'open' ? 'ok' : 'bad'">
          事件流 {{ state.stream }} · {{ state.events.length }}
        </span>
        <span class="chip">stage {{ state.health?.stage ?? "—" }}</span>
        <span class="chip mono">{{ state.health?.channel ?? "no channel" }}</span>
        <span class="chip mono">{{ state.health?.window_id ?? "no window" }}</span>
        <button @click="refresh()">重新读取</button>
      </div>
    </header>

    <p v-if="unreachable" class="banner bad">
      控制平面不可达（{{ state.errors.health }}）。先启动：
      <code>python apps/desktop-agent/main.py</code>，页面通过 Vite 代理 <code>/api</code> 访问它。
    </p>
    <!-- Saying which channel produced the data is what keeps a pre-G1 demo from reading as live proof. -->
    <p v-else-if="simulated" class="banner warn">
      当前通道 <code>{{ state.health?.channel }}</code>：元素、会话文本与状态都来自
      <code>tests/fixtures/trae/dom_ide_idle.json</code> 的确定性模拟，不是真实 Trae 观测（gate G1 之前只有这一种）。
    </p>

    <nav class="tabs">
      <button
        v-for="tab in TABS"
        :key="tab.id"
        :class="{ active: active === tab.id }"
        @click="active = tab.id"
      >
        {{ tab.label }}
        <span v-if="tab.id === 'approvals' && state.pending.length" class="badge">{{ state.pending.length }}</span>
      </button>
    </nav>

    <component :is="current.view" />

    <footer class="muted">
      这个页面不判定任何状态：submitted / running / claimed_done / failed / verified 全部来自控制平面写入的事件，
      其中 <code>verified</code> 只有独立验证器写得动（docs/agent.md 状态语义、docs/sql.md）。
    </footer>
  </main>
</template>

<style scoped>
.shell { max-width: 1280px; margin: 0 auto; padding: 16px 20px 40px; }
.bar { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; flex-wrap: wrap; }
.brand h1 { font-size: 18px; margin: 0 0 2px; }
.brand p { margin: 0; font-size: 12px; }
.chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.chip {
  font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: var(--muted);
}
.chip.ok { color: var(--ok); }
.chip.bad { color: var(--err); }
.banner { margin: 12px 0 0; border-radius: 6px; padding: 8px 10px; font-size: 12px; }
.banner.warn { border: 1px dashed var(--warn); color: var(--warn); }
.banner.bad { border: 1px solid var(--err); color: var(--err); }
.tabs { display: flex; gap: 6px; margin: 18px 0 14px; border-bottom: 1px solid var(--line); }
.tabs button {
  background: none; border: none; border-bottom: 2px solid transparent; padding: 8px 10px;
  color: var(--muted); cursor: pointer; font: inherit;
}
.tabs button.active { color: var(--fg); border-bottom-color: var(--accent); }
.badge { background: var(--warn); color: #201c00; border-radius: 999px; padding: 0 6px; font-size: 11px; margin-left: 4px; }
footer { margin-top: 26px; font-size: 11px; border-top: 1px solid var(--line); padding-top: 10px; }
</style>

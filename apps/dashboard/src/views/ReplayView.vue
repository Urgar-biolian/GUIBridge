<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { state } from "../state";
import EvidenceList from "../components/EvidenceList.vue";
import JsonBlock from "../components/JsonBlock.vue";
import type { GuiEvent } from "../api";

const STEP_MS = 600;

const kind = ref("");
const taskId = ref("");
const text = ref("");
const cursor = ref(0);
const playing = ref(false);
let timer: number | null = null;

const kinds = computed(() => [...new Set(state.events.map((event) => event.kind))].sort());

const filtered = computed(() =>
  state.events.filter((event) => {
    if (kind.value && event.kind !== kind.value) return false;
    if (taskId.value && event.task_id !== taskId.value) return false;
    if (text.value) {
      const haystack = `${event.semantic_id ?? ""} ${event.action ?? ""} ${event.window_id ?? ""} ${JSON.stringify(event.payload)}`;
      if (!haystack.toLowerCase().includes(text.value.toLowerCase())) return false;
    }
    return true;
  }),
);

const current = computed<GuiEvent | null>(() => filtered.value[Math.min(cursor.value, Math.max(filtered.value.length - 1, 0))] ?? null);

watch(() => filtered.value.length, (length) => {
  if (length === 0) cursor.value = 0;
  else if (cursor.value > length - 1) cursor.value = length - 1;
});

function stop(): void {
  playing.value = false;
  if (timer !== null) window.clearInterval(timer);
  timer = null;
}

function toggle(): void {
  if (playing.value) {
    stop();
    return;
  }
  playing.value = true;
  timer = window.setInterval(() => {
    if (cursor.value >= filtered.value.length - 1) stop();
    else cursor.value += 1;
  }, STEP_MS);
}

onUnmounted(stop);

function select(index: number): void {
  stop();
  cursor.value = index;
}

function clock(ts: string): string {
  return ts.replace("T", " ").slice(11, 19);
}
</script>

<template>
  <div class="replay">
    <section class="controls">
      <div class="row">
        <label>kind
          <select v-model="kind">
            <option value="">全部</option>
            <option v-for="entry in kinds" :key="entry" :value="entry">{{ entry }}</option>
          </select>
        </label>
        <label>task_id <input v-model="taskId" class="mono" placeholder="task_…" /></label>
        <label>搜索 <input v-model="text" placeholder="semantic_id / 文本" /></label>
      </div>
      <div class="row">
        <button @click="cursor = Math.max(cursor - 1, 0)">◀ 上一步</button>
        <button @click="toggle">{{ playing ? "⏸ 暂停" : "▶ 步进回放" }}</button>
        <button @click="cursor = Math.min(cursor + 1, Math.max(filtered.length - 1, 0))">下一步 ▶</button>
        <input v-model.number="cursor" type="range" min="0" :max="Math.max(filtered.length - 1, 0)" class="scrub" />
        <span class="muted">{{ filtered.length ? cursor + 1 : 0 }} / {{ filtered.length }} 条</span>
      </div>
      <p class="note muted">
        回放的是事件存储里按 seq 追加的审计流（含动作前后快照摘要），不是录屏；
        事件只追加不更新（docs/sql.md），所以这条时间线可信到什么程度取决于写入它的那一侧。
      </p>
      <p v-if="state.errors.events" class="error">事件流异常：{{ state.errors.events }}</p>
    </section>

    <section class="split">
      <ol class="stream">
        <li
          v-for="(event, index) in filtered"
          :key="event.event_id"
          :class="{ active: index === cursor }"
          @click="select(index)"
        >
          <span class="seq">{{ event.seq }}</span>
          <span class="kind">{{ event.kind }}</span>
          <span class="mono small">
            {{ event.semantic_id ?? event.window_id ?? event.task_id ?? "" }}
            {{ event.action ? `·${event.action}` : "" }}
          </span>
          <span class="muted small">{{ clock(event.ts) }}</span>
        </li>
      </ol>

      <article v-if="current" class="pane">
        <h3>{{ current.kind }} <span class="muted small">#{{ current.seq }}</span></h3>
        <dl class="meta">
          <div><dt>事件 ID</dt><dd class="mono">{{ current.event_id }}</dd></div>
          <div><dt>时间</dt><dd>{{ current.ts }}</dd></div>
          <div><dt>任务</dt><dd class="mono">{{ current.task_id ?? "—" }}</dd></div>
          <div><dt>窗口</dt><dd class="mono">{{ current.window_id ?? "—" }}</dd></div>
          <div><dt>语义 ID / 动作</dt><dd class="mono">{{ current.semantic_id ?? "—" }} {{ current.action ?? "" }}</dd></div>
          <div><dt>审批</dt><dd class="mono">{{ current.approval_id ?? "—" }}</dd></div>
        </dl>
        <h4>前后证据</h4>
        <EvidenceList :event="current" />
        <h4>payload</h4>
        <JsonBlock :value="current.payload" />
      </article>
      <article v-else class="pane">
        <p class="muted">没有匹配的事件。</p>
      </article>
    </section>
  </div>
</template>

<style scoped>
.replay { display: flex; flex-direction: column; gap: 12px; }
.controls { display: flex; flex-direction: column; gap: 8px; }
.note { font-size: 12px; margin: 0; }
.scrub { flex: 1; }
.split { display: grid; grid-template-columns: 380px 1fr; gap: 16px; align-items: start; }
.stream { list-style: none; margin: 0; padding: 0; max-height: 60vh; overflow: auto; border: 1px solid var(--line); border-radius: 6px; }
.stream li { display: grid; grid-template-columns: 46px 130px 1fr 88px; gap: 6px; padding: 4px 8px; font-size: 12px; border-bottom: 1px solid var(--line); cursor: pointer; }
.stream li.active { background: var(--panel-2); border-left: 2px solid var(--accent); }
.stream .kind { color: var(--accent); }
.small { font-size: 11px; }
.pane { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.pane h3 { margin: 0 0 8px; font-size: 15px; }
.pane h4 { margin: 14px 0 4px; font-size: 13px; color: var(--muted); }
.meta { display: grid; grid-template-columns: 120px 1fr; gap: 2px 10px; margin: 0; font-size: 12px; }
.meta dt { color: var(--muted); }
.meta dd { margin: 0; }
</style>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../api";
import type { TaskResult, TaskStatus, VerificationPayload } from "../api";
import { state } from "../state";
import EvidenceList from "../components/EvidenceList.vue";
import JsonBlock from "../components/JsonBlock.vue";
import StateTag from "../components/StateTag.vue";

const selectedId = ref<string | null>(null);
const status = ref<TaskStatus | null>(null);
const result = ref<TaskResult | null>(null);
const detailError = ref("");
const loading = ref(false);

const selected = computed(() => state.tasks.find((task) => task.task_id === selectedId.value) ?? null);

const verifications = computed(() =>
  state.events.filter((event) => event.kind === "verify" && event.task_id === selectedId.value),
);

const taskEvents = computed(() =>
  [...state.events].reverse().filter((event) => event.task_id === selectedId.value).slice(0, 60),
);

const latestVerification = computed<VerificationPayload | null>(() => {
  const last = verifications.value[0];
  return last ? (last.payload as VerificationPayload) : null;
});

const failure = computed(() => {
  const last = [...state.events].reverse().find(
    (event) => event.kind === "task_failed" && event.task_id === selectedId.value,
  );
  return last ? (last.payload as { error_code?: string; message?: string; failure_class?: string }) : null;
});

watch(
  () => state.tasks.map((task) => `${task.task_id}:${task.state}`).join("|"),
  () => {
    if (!selectedId.value && state.tasks.length) selectedId.value = state.tasks[0].task_id;
  },
  { immediate: true },
);

async function open(taskId: string): Promise<void> {
  selectedId.value = taskId;
  status.value = null;
  result.value = null;
  detailError.value = "";
  loading.value = true;
  try {
    status.value = await api.taskStatus(taskId);
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : String(error);
  } finally {
    loading.value = false;
  }
}

async function readReply(): Promise<void> {
  if (!selectedId.value) return;
  detailError.value = "";
  try {
    result.value = await api.taskResult(selectedId.value);
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : String(error);
  }
}

function clock(ts: string): string {
  return ts.replace("T", " ").slice(11, 19);
}
</script>

<template>
  <div class="tasks">
    <section class="list">
      <header class="row">
        <h2>任务</h2>
        <span class="muted">{{ state.tasks.length }} 条</span>
      </header>
      <p v-if="state.errors.tasks" class="error">读取失败：{{ state.errors.tasks }}</p>
      <p v-else-if="!state.tasks.length" class="muted">
        当前事件库没有任务。Dashboard 只读展示 + 审批（docs/framework.md S4 约束），提交任务请用
        <code>examples/handoff_demo.py</code> 或 MCP 工具 <code>trae.send_task</code>。
      </p>
      <button
        v-for="task in state.tasks"
        :key="task.task_id"
        class="task"
        :class="{ active: task.task_id === selectedId }"
        @click="open(task.task_id)"
      >
        <StateTag :state="task.state" />
        <span class="mono">{{ task.task_id }}</span>
        <span class="muted">{{ clock(task.updated_ts) }} · {{ task.mode }}</span>
      </button>
    </section>

    <section v-if="selected" class="detail">
      <h2>{{ selected.task_id }}</h2>
      <dl class="meta">
        <div><dt>状态</dt><dd><StateTag :state="selected.state" /></dd></div>
        <div><dt>应用</dt><dd>{{ selected.app }} · {{ selected.mode }}</dd></div>
        <div><dt>工作区</dt><dd class="mono">{{ selected.project_path }}</dd></div>
        <div><dt>创建 / 更新</dt><dd>{{ clock(selected.created_ts) }} → {{ clock(selected.updated_ts) }}</dd></div>
        <div v-if="selected.acceptance"><dt>验收条件</dt><dd><JsonBlock :value="selected.acceptance" label="acceptance" collapsed /></dd></div>
      </dl>

      <h3>状态迁移时间线</h3>
      <ol class="timeline">
        <li v-for="(step, index) in selected.transitions" :key="index">
          <StateTag :state="step.state" />
          <span>{{ clock(step.ts) }}</span>
          <span class="mono muted" :title="step.evidence_id">{{ step.evidence_id || "无证据 ID" }}</span>
        </li>
      </ol>
      <!-- The absence of `verified` is the finding; say it instead of leaving a short list unexplained. -->
      <p v-if="!selected.transitions.some((step) => step.state === 'verified')" class="warn">
        还没有 <code>verified</code> 迁移：界面上的「自称完成」不等于交付（docs/agent.md 状态语义）。
      </p>
      <div v-if="failure" class="failure">
        <p>
          <strong class="no">{{ failure.error_code }}</strong>
          <span class="muted">{{ failure.failure_class ? ` · ${failure.failure_class}` : "" }}</span>
        </p>
        <p class="muted">{{ failure.message }}</p>
        <p class="note muted">
          这是 S2 的既有语义：缺审批 token 时适配器直接写 <code>failed</code> 而不是
          <code>awaiting_approval</code>，因为审批提示的 DOM 特征尚未实测
          （docs/dev-status.md S2 未达成项 4）。右侧「审批与窗口」里能看到同一时刻写入的待审批请求。
        </p>
      </div>

      <h3>实时信号</h3>
      <div class="row">
        <button :disabled="loading" @click="open(selected.task_id)">重新读取状态</button>
        <span v-if="loading" class="muted">读取中…</span>
      </div>
      <p v-if="detailError" class="error">{{ detailError }}</p>
      <table v-if="status" class="signals">
        <tbody>
          <tr v-for="(value, key) in status.signals" :key="key">
            <th>{{ key }}</th>
            <td :class="value ? 'yes' : 'no'">{{ value }}</td>
          </tr>
        </tbody>
      </table>

      <h3>执行侧回复</h3>
      <button @click="readReply">trae.read_result（不可信文本）</button>
      <div v-if="result" class="reply">
        <p class="banner">
          untrusted={{ result.untrusted }} · claimed_done={{ result.claimed_done }}
          · 截断={{ result.truncated }}（全长 {{ result.full_length }}）
        </p>
        <!-- Rendered as text only. Nothing here is parsed, linked or executed: docs/agent.md 提示注入防护. -->
        <pre class="reply-text">{{ result.reply_text }}</pre>
      </div>

      <h3>独立验证器报告</h3>
      <div v-if="latestVerification" class="verify">
        <p>
          <strong :class="latestVerification.verified ? 'yes' : 'no'">
            {{ latestVerification.verified ? "verified" : latestVerification.status }}
          </strong>
          <span class="muted">
            · 变更 {{ (latestVerification.changed_files ?? []).length }} 个文件
            · 越界 {{ (latestVerification.out_of_scope ?? []).length }} 个
            · 原因 {{ (latestVerification.reasons ?? []).join("；") || "无" }}
          </span>
        </p>
        <ul class="files">
          <li v-for="file in latestVerification.changed_files ?? []" :key="file" class="mono">{{ file }}</li>
        </ul>
        <JsonBlock :value="latestVerification" label="verify 证据（Git + 退出码，不含回复文本）" collapsed />
      </div>
      <p v-else class="muted">该任务没有 verifier 写入的 <code>verify</code> 事件。</p>

      <h3>相关事件</h3>
      <table class="events">
        <thead><tr><th>seq</th><th>时间</th><th>kind</th><th>动作</th><th>证据</th></tr></thead>
        <tbody>
          <tr v-for="event in taskEvents" :key="event.event_id">
            <td>{{ event.seq }}</td>
            <td>{{ clock(event.ts) }}</td>
            <td>{{ event.kind }}</td>
            <td class="mono">{{ event.semantic_id ?? "" }} {{ event.action ?? "" }}</td>
            <td><EvidenceList :event="event" /></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-else class="detail">
      <p class="muted">选择左侧任务查看迁移链、回复文本与验证证据。</p>
    </section>
  </div>
</template>

<style scoped>
.tasks { display: grid; grid-template-columns: 260px 1fr; gap: 18px; align-items: start; }
.list { display: flex; flex-direction: column; gap: 6px; }
.task {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  padding: 8px; color: inherit; text-align: left; cursor: pointer; font: inherit;
}
.task.active { border-color: var(--accent); }
.detail h2 { margin: 0 0 10px; font-size: 17px; }
.detail h3 { margin: 20px 0 6px; font-size: 14px; color: var(--muted); text-transform: none; }
.meta { display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; margin: 0; }
.meta dt { color: var(--muted); font-size: 12px; }
.meta dd { margin: 0; font-size: 13px; }
.timeline { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--line); }
.timeline li { display: flex; gap: 10px; align-items: baseline; padding: 4px 0 4px 12px; font-size: 13px; }
.signals, .events { border-collapse: collapse; width: 100%; font-size: 12px; }
.signals th, .signals td, .events th, .events td { border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }
.signals th { color: var(--muted); font-weight: 500; width: 180px; }
.events td { vertical-align: top; }
.reply { margin-top: 8px; }
.banner { color: var(--warn); font-size: 12px; margin: 0 0 4px; }
.reply-text {
  white-space: pre-wrap; word-break: break-word; background: var(--panel-2);
  border: 1px dashed var(--warn); border-radius: 6px; padding: 8px; font-size: 12px; max-height: 260px; overflow: auto;
}
.files { margin: 6px 0; padding-left: 18px; font-size: 12px; }
.failure { border: 1px solid var(--line); border-left: 3px solid var(--err); border-radius: 6px; padding: 8px 10px; margin-top: 10px; font-size: 12px; }
.failure p { margin: 3px 0; }
.note { font-size: 12px; margin: 4px 0 0; }
.yes { color: var(--ok); }
.no { color: var(--err); }
</style>

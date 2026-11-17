<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

type Task = {
  task_id: string;
  state: string;
  mode: string;
  project_path: string;
  updated_ts?: string;
  transitions?: { state: string; ts: string }[];
};
type EventRow = {
  event_id: string; ts: string; kind: string; task_id?: string;
  payload?: Record<string, unknown>;
};
type Locator = { semantic_id: string; app_version: string; verification?: string };
type HealPatch = {
  patch_id: string; semantic_id: string; app_version: string;
  proposed_chain: unknown[]; status: string; created_ts: string;
};
type Approval = { approval_id: string; scope?: Record<string, unknown>; expires_ts?: string };

const agentStatus = ref("checking…");
const tasks = ref<Task[]>([]);
const selected = ref<string | null>(null);
const selectedTask = ref<Task | null>(null);
const events = ref<EventRow[]>([]);
const locators = ref<Locator[]>([]);
const healPatches = ref<HealPatch[]>([]);
const approvals = ref<Approval[]>([]);
const approvalSemantic = ref("");
const approvalAction = ref("");
const grantedToken = ref("");
const error = ref("");

let stream: EventSource | null = null;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await r.json();
  if (!r.ok) throw new Error(body.message || body.detail || r.statusText);
  return body as T;
}

async function loadAll() {
  try {
    const [t, l, a] = await Promise.all([
      api<{ tasks: Task[] }>("/tasks"),
      api<{ locators: Locator[]; heal_patches: HealPatch[] }>("/locators"),
      api<{ approvals: Approval[] }>("/approvals/pending"),
    ]);
    tasks.value = t.tasks;
    locators.value = l.locators;
    healPatches.value = l.heal_patches;
    approvals.value = a.approvals;
    if (selected.value) await selectTask(selected.value);
  } catch (e) {
    error.value = String(e);
  }
}

async function selectTask(id: string) {
  selected.value = id;
  selectedTask.value = await api<Task>(`/tasks/${id}`);
}

const taskEvents = computed(() =>
  events.value.filter((e) => !selected.value || e.task_id === selected.value).slice(-80).reverse()
);

function connect() {
  stream = new EventSource("/api/events");
  stream.onmessage = (msg) => {
    const evt = JSON.parse(msg.data) as EventRow;
    events.value.push(evt);
    if (evt.kind === "status_observed" || evt.kind === "task_submitted") loadAll();
    if (evt.kind === "approval_created") loadAll();
  };
  stream.onerror = () => {
    agentStatus.value = "stream disconnected";
  };
}

async function grant() {
  error.value = "";
  try {
    const res = await api<{ token: string }>("/approvals", {
      method: "POST",
      body: JSON.stringify({
        semantic_id: approvalSemantic.value || null,
        action: approvalAction.value || null,
        ttl_seconds: 600,
      }),
    });
    grantedToken.value = res.token;
    approvalSemantic.value = "";
    approvalAction.value = "";
    await loadAll();
  } catch (e) {
    error.value = String(e);
  }
}

async function review(patch: HealPatch, action: "approve" | "reject") {
  error.value = "";
  try {
    await api(`/locators/${patch.semantic_id}/heal-review`, {
      method: "POST",
      body: JSON.stringify({ patch_id: patch.patch_id, action }),
    });
    await loadAll();
  } catch (e) {
    error.value = String(e);
  }
}

onMounted(async () => {
  try {
    const h = await api<{ status: string }>("/health");
    agentStatus.value = h.status === "ok" ? "connected" : "unreachable";
  } catch {
    agentStatus.value = "unreachable";
    return;
  }
  await loadAll();
  connect();
});

onBeforeUnmount(() => stream?.close());
</script>

<template>
  <main class="shell">
    <header>
      <h1>GUIBridge Dashboard</h1>
      <p class="status">desktop-agent: <b>{{ agentStatus }}</b></p>
      <p v-if="error" class="error">{{ error }}</p>
    </header>

    <section>
      <h2>任务与状态迁移</h2>
      <table>
        <thead><tr><th>task</th><th>state</th><th>mode</th><th>project</th></tr></thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id" @click="selectTask(t.task_id)"
              :class="{ active: t.task_id === selected }">
            <td class="mono">{{ t.task_id }}</td>
            <td><span class="state">{{ t.state }}</span></td>
            <td>{{ t.mode }}</td>
            <td class="mono small">{{ t.project_path }}</td>
          </tr>
          <tr v-if="!tasks.length"><td colspan="4" class="muted">暂无任务</td></tr>
        </tbody>
      </table>
      <div v-if="selectedTask" class="timeline">
        <h3>迁移链 {{ selectedTask.task_id }}</h3>
        <ol>
          <li v-for="(tr, i) in selectedTask.transitions || []" :key="i">
            <span class="mono">{{ tr.ts }}</span> → <b>{{ tr.state }}</b>
          </li>
        </ol>
      </div>
    </section>

    <section>
      <h2>事件回放（SSE）</h2>
      <p class="muted small">显示最近 80 条；动作事件中的 before/after snapshot id 即证据引用。</p>
      <ul class="events">
        <li v-for="e in taskEvents" :key="e.event_id">
          <span class="mono">{{ e.ts }}</span>
          <b>{{ e.kind }}</b>
          <span class="mono small">{{ e.task_id || "" }}</span>
          <pre v-if="e.payload">{{ JSON.stringify(e.payload) }}</pre>
        </li>
        <li v-if="!taskEvents.length" class="muted">暂无事件</li>
      </ul>
    </section>

    <section>
      <h2>审批待办</h2>
      <ul>
        <li v-for="a in approvals" :key="a.approval_id" class="mono">
          {{ a.approval_id }} · {{ JSON.stringify(a.scope) }} · exp {{ a.expires_ts }}
        </li>
        <li v-if="!approvals.length" class="muted">无待审批</li>
      </ul>
      <form @submit.prevent="grant">
        <input v-model="approvalSemantic" placeholder="semantic_id" />
        <input v-model="approvalAction" placeholder="action" />
        <button type="submit">授予一次性审批（600s）</button>
      </form>
      <p v-if="grantedToken" class="token">token（仅显示一次）：<span class="mono">{{ grantedToken }}</span></p>
    </section>

    <section>
      <h2>定位器与修复记录</h2>
      <table>
        <thead><tr><th>semantic_id</th><th>app_version</th><th>verification</th></tr></thead>
        <tbody>
          <tr v-for="l in locators" :key="l.semantic_id">
            <td class="mono">{{ l.semantic_id }}</td>
            <td>{{ l.app_version }}</td>
            <td>{{ l.verification }}</td>
          </tr>
        </tbody>
      </table>
      <h3>pending heal patches</h3>
      <table>
        <thead><tr><th>patch_id</th><th>semantic_id</th><th>status</th><th>created</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in healPatches" :key="p.patch_id">
            <td class="mono small">{{ p.patch_id }}</td>
            <td class="mono">{{ p.semantic_id }}</td>
            <td>{{ p.status }}</td>
            <td class="mono small">{{ p.created_ts }}</td>
            <td>
              <button @click="review(p, 'approve')">approve</button>
              <button @click="review(p, 'reject')" class="secondary">reject</button>
            </td>
          </tr>
          <tr v-if="!healPatches.length"><td colspan="5" class="muted">无修复补丁</td></tr>
        </tbody>
      </table>
    </section>
  </main>
</template>

<style>
:root { color-scheme: light dark; }
body { margin: 0; background: #0f1216; color: #e6e8eb; }
.shell { font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #2a2f36; padding-bottom: .3rem; }
.status { color: #9aa4b2; }
.error { color: #ff6b6b; }
.muted { color: #7d8794; }
.small { font-size: .8rem; }
.mono { font-family: ui-monospace, monospace; }
table { width: 100%; border-collapse: collapse; margin-top: .5rem; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #22272e; font-size: .9rem; }
tbody tr { cursor: pointer; }
tbody tr.active { background: #1b2430; }
.state { padding: .1rem .4rem; border-radius: 4px; background: #24303d; }
.timeline ol { padding-left: 1.2rem; }
.events { list-style: none; padding: 0; max-height: 420px; overflow: auto; }
.events li { border-bottom: 1px solid #1c2127; padding: .3rem 0; }
.events pre { margin: .2rem 0 0; font-size: .75rem; color: #9fb0c3; white-space: pre-wrap; }
form { display: flex; gap: .5rem; margin-top: .6rem; }
input { background: #171c22; color: #e6e8eb; border: 1px solid #2a313a; padding: .3rem .5rem; }
button { background: #2456a6; color: white; border: 0; padding: .35rem .7rem; border-radius: 4px; cursor: pointer; }
button.secondary { background: #5a3030; margin-left: .3rem; }
.token { color: #7fdc9a; }
</style>

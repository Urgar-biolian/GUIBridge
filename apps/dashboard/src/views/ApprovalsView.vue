<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api";
import type { ApprovalScope, GuiEvent, SnapshotCapture, WindowRecord } from "../api";
import { refresh, state } from "../state";
import JsonBlock from "../components/JsonBlock.vue";

interface Granted {
  approvalId: string;
  grantedBy: string;
  expires: string;
  scope: ApprovalScope;
}

const busy = ref("");
const error = ref("");
const issued = ref<{ token: string; scope: ApprovalScope; request_id: string | null } | null>(null);
const captured = ref<Record<string, SnapshotCapture>>({});

const granted = computed<Granted[]>(() =>
  state.events
    .filter((event) => event.kind === "approval_granted")
    .map((event) => ({
      approvalId: String(event.payload.approval_id ?? event.approval_id ?? ""),
      grantedBy: String(event.payload.granted_by ?? "user"),
      expires: String(event.payload.expires_ts ?? ""),
      scope: (event.payload.scope ?? {}) as ApprovalScope,
    }))
    .reverse(),
);

const consumed = computed<string[]>(() =>
  state.events.filter((event) => event.kind === "approval_consumed").map((event) => String(event.payload.approval_id ?? "")),
);

const mcpCalls = computed(() =>
  [...state.events].reverse().filter((event) => event.kind === "mcp_call").slice(0, 40),
);

const pendingByWindow = computed(() => state.windows.filter((window) => !window.whitelisted));

function scopeText(scope: ApprovalScope): string {
  return [
    scope.window_id ? `window=${scope.window_id}` : "",
    (scope.semantic_ids ?? []).length ? `semantic=${(scope.semantic_ids ?? []).join(",")}` : "",
    (scope.actions ?? []).length ? `action=${(scope.actions ?? []).join(",")}` : "",
  ].filter(Boolean).join(" · ") || "（整个窗口）";
}

function clock(ts: string): string {
  return ts.replace("T", " ").slice(11, 19);
}

async function approve(event: GuiEvent & { payload: { request_id: string; scope: ApprovalScope; reason: string } }): Promise<void> {
  busy.value = event.payload.request_id;
  error.value = "";
  try {
    const outcome = await api.grantApproval(event.payload.scope, event.payload.request_id, "dashboard");
    issued.value = { token: outcome.token, scope: outcome.scope, request_id: event.payload.request_id };
    await refresh();
  } catch (problem) {
    error.value = problem instanceof Error ? problem.message : String(problem);
  } finally {
    busy.value = "";
  }
}

async function copy(): Promise<void> {
  if (!issued.value) return;
  try {
    await navigator.clipboard.writeText(issued.value.token);
  } catch {
    error.value = "剪贴板不可用：请手动选中复制（本地 loopback 页面，不经网络）";
  }
}

async function allowWindow(window: WindowRecord): Promise<void> {
  busy.value = window.window_id;
  error.value = "";
  try {
    await api.whitelist(window.window_id);
    await refresh();
  } catch (problem) {
    error.value = problem instanceof Error ? problem.message : String(problem);
  } finally {
    busy.value = "";
  }
}

async function capture(window: WindowRecord): Promise<void> {
  busy.value = window.window_id;
  error.value = "";
  try {
    captured.value = { ...captured.value, [window.window_id]: await api.captureSnapshot(window.window_id) };
  } catch (problem) {
    error.value = problem instanceof Error ? problem.message : String(problem);
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <div class="approvals">
    <section>
      <h2>待审批请求 <span class="muted">{{ state.pending.length }} 条</span></h2>
      <p class="note muted">
        请求由安全门在高影响动作缺 token 时写入事件存储；这里只是把人的决定换成一次性 token，
        Dashboard 不会替人默认同意（docs/PRD.md §9）。
      </p>
      <p v-if="state.errors.approvals" class="error">{{ state.errors.approvals }}</p>
      <p v-else-if="!state.pending.length" class="muted">没有待审批请求。</p>
      <ul v-else class="requests">
        <li v-for="request in state.pending" :key="request.event_id">
          <div class="head">
            <strong class="mono">{{ request.payload.scope.semantic_ids?.join(", ") || request.payload.scope.window_id }}</strong>
            <span class="muted">{{ request.action ?? "" }} · {{ clock(request.ts) }}</span>
          </div>
          <p class="reason">{{ request.payload.reason }}</p>
          <p class="scope mono">{{ scopeText(request.payload.scope) }}</p>
          <button :disabled="busy === request.payload.request_id" @click="approve(request)">
            批准（授予一次性 token）
          </button>
        </li>
      </ul>

      <div v-if="issued" class="token">
        <p>
          已授予 <code>{{ issued.request_id }}</code>。token 单次使用、约 10 分钟内有效，
          且只在本机 loopback 上出现——不要粘贴进聊天或文档（那些是不可信侧）。
        </p>
        <code class="token-value">{{ issued.token }}</code>
        <button @click="copy">复制</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </section>

    <section>
      <h2>审批历史 <span class="muted">已授予 {{ granted.length }} · 已消费 {{ consumed.length }}</span></h2>
      <table v-if="granted.length">
        <thead><tr><th>approval_id</th><th>范围</th><th>授予者</th><th>到期</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="entry in granted" :key="entry.approvalId">
            <td class="mono">{{ entry.approvalId }}</td>
            <td class="mono small">{{ scopeText(entry.scope) }}</td>
            <td>{{ entry.grantedBy }}</td>
            <td>{{ clock(entry.expires) }}</td>
            <td :class="consumed.includes(entry.approvalId) ? 'used' : 'fresh'">
              {{ consumed.includes(entry.approvalId) ? "已用于一次动作" : "未使用" }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">本轮还没有授予过审批。</p>
    </section>

    <section>
      <h2>窗口白名单</h2>
      <p class="note muted">
        只有白名单窗口可被检查或操作；把窗口加进来是需要人来做的安全决定。
      </p>
      <p v-if="state.errors.windows" class="error">{{ state.errors.windows }}</p>
      <table v-else>
        <thead>
          <tr><th>window_id</th><th>进程</th><th>标题</th><th>几何</th><th>白名单</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="window in state.windows" :key="window.window_id">
            <td class="mono">{{ window.window_id }}</td>
            <td class="mono">{{ window.process_name }}</td>
            <td>{{ window.title }}</td>
            <td class="mono small">{{ JSON.stringify(window.geometry) }}</td>
            <td :class="window.whitelisted ? 'yes' : 'no'">{{ window.whitelisted ? "是" : "否" }}</td>
            <td class="actions">
              <button v-if="!window.whitelisted" :disabled="busy === window.window_id" @click="allowWindow(window)">
                加入白名单
              </button>
              <button :disabled="busy === window.window_id" @click="capture(window)">捕获快照</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-for="(body, id) in captured" :key="id" class="capture">
        <strong class="mono">{{ id }}</strong>
        <span class="muted"> · {{ body.snapshot_id }} · {{ clock(body.ts) }}</span>
        <p>元素 {{ body.elements_summary.count }} 个；角色 {{ body.elements_summary.roles.join(", ") || "—" }}</p>
        <p class="muted small">
          截图：{{ body.image_path ?? "无（当前通道不产图；pre-G1 模拟通道本就如此）" }}
        </p>
      </div>
    </section>

    <section>
      <h2>最近 MCP 调用 <span class="muted">含被拒的调用</span></h2>
      <table v-if="mcpCalls.length">
        <thead><tr><th>seq</th><th>时间</th><th>工具</th><th>参数摘要</th><th>结果</th></tr></thead>
        <tbody>
          <tr v-for="entry in mcpCalls" :key="entry.event_id">
            <td>{{ entry.seq }}</td>
            <td>{{ clock(entry.ts) }}</td>
            <td class="mono">{{ entry.payload.tool }}</td>
            <td class="mono small">{{ JSON.stringify(entry.payload.params) }}</td>
            <td>
              <span :class="entry.payload.ok ? 'yes' : 'error'">{{ entry.payload.ok ? "已执行" : `被拒 ${entry.payload.error_code}` }}</span>
              <JsonBlock :value="entry.payload" label="详情" collapsed />
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">还没有 MCP 调用（stdio 客户端未连接时这里就是空的）。</p>
    </section>
  </div>
</template>

<style scoped>
.approvals { display: flex; flex-direction: column; gap: 22px; }
h2 { font-size: 15px; margin: 0 0 4px; }
.note { font-size: 12px; margin: 0 0 8px; }
.requests { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.requests li { border: 1px solid var(--line); border-left: 3px solid var(--warn); border-radius: 6px; padding: 10px; background: var(--panel); }
.head { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.reason, .scope { margin: 6px 0; font-size: 12px; }
.scope { color: var(--muted); }
.token { margin-top: 12px; border: 1px dashed var(--ok); border-radius: 6px; padding: 10px; font-size: 12px; }
.token-value { display: block; word-break: break-all; background: var(--panel-2); padding: 6px; border-radius: 4px; margin: 6px 0; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; }
.actions button { margin-right: 6px; }
.capture { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; margin-top: 8px; font-size: 12px; }
.capture p { margin: 4px 0 0; }
.yes { color: var(--ok); }
.no, .used { color: var(--muted); }
.fresh { color: var(--info); }
.small { font-size: 11px; }
</style>

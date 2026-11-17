<script setup lang="ts">
import { computed } from "vue";
import type { GuiEvent, SnapshotEvidence } from "../api";

const props = defineProps<{ event: GuiEvent }>();

const ROLE: Record<string, string> = { before: "动作前", after: "动作后" };

/** `action` events carry their own before/after summary; other kinds only carry ids. */
const snapshots = computed<SnapshotEvidence[]>(() => props.event.payload.snapshots ?? []);

const rows = computed(() =>
  snapshots.value.map((entry, index) => ({ ...entry, role: index === 0 ? "before" : "after" })),
);

const bareIds = computed(() =>
  snapshots.value.length ? [] : props.event.evidence.filter((id) => typeof id === "string" && id),
);

function short(id: string): string {
  return id.length > 22 ? `${id.slice(0, 10)}…${id.slice(-8)}` : id;
}

function time(ts: string): string {
  return ts.replace("T", " ").slice(11, 23);
}

function label(role: string): string {
  return ROLE[role] ?? role;
}
</script>

<template>
  <div class="evidence">
    <table v-if="rows.length">
      <thead>
        <tr><th>时点</th><th>快照</th><th>元素数</th><th>截图</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.snapshot_id">
          <td>{{ label(row.role) }}</td>
          <td class="mono" :title="`${row.snapshot_id} · ${row.ts}`">{{ short(row.snapshot_id) }}</td>
          <td>{{ row.element_count }}</td>
          <td class="mono" :title="row.image_path ?? ''">
            <span v-if="row.image_path">{{ short(row.image_path) }}</span>
            <!-- The pre-G1 channel captures no pixels; saying so beats an empty <img> that looks broken. -->
            <span v-else class="none">无截图（通道 image_path 为空）</span>
          </td>
        </tr>
      </tbody>
    </table>
    <ul v-else-if="bareIds.length" class="ids">
      <li v-for="id in bareIds" :key="id" class="mono" :title="id">{{ short(id) }}</li>
    </ul>
    <p v-else class="none">该事件没有证据引用。</p>
  </div>
</template>

<style scoped>
.evidence table { width: 100%; border-collapse: collapse; font-size: 12px; }
.evidence th, .evidence td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--line); }
.evidence th { color: var(--muted); font-weight: 500; }
.ids { list-style: none; display: flex; flex-wrap: wrap; gap: 6px; padding: 0; margin: 0; }
.ids li { background: var(--panel-2); border: 1px solid var(--line); border-radius: 4px; padding: 2px 6px; }
.none { color: var(--muted); font-size: 12px; margin: 0; }
</style>

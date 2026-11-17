<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api";
import type { ChainStrategy, HealPatch, LocatorRecord } from "../api";
import { refresh, state } from "../state";

const busy = ref("");
const message = ref("");

const pending = computed(() => state.registry.heal_patches.filter((patch) => patch.status === "pending"));
const reviewed = computed(() => state.registry.heal_patches.filter((patch) => patch.status !== "pending"));

const bySemantic = computed(() => {
  const map = new Map<string, HealPatch[]>();
  for (const patch of state.registry.heal_patches) {
    map.set(patch.semantic_id, [...(map.get(patch.semantic_id) ?? []), patch]);
  }
  return map;
});

function chain(locator: LocatorRecord): ChainStrategy[] {
  return locator.chain ?? [];
}

function strategies(items: ChainStrategy[]): string {
  return items
    .map((entry) => Object.entries(entry).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(" "))
    .join("  |  ");
}

async function decide(patch: HealPatch, decision: "approved" | "rejected"): Promise<void> {
  busy.value = patch.patch_id;
  message.value = "";
  try {
    const outcome = await api.reviewHealPatch(patch.semantic_id, patch.patch_id, decision, "dashboard");
    message.value = `${outcome.patch_id} → ${outcome.status}（写入 heal_reviewed 事件）`;
    await refresh();
  } catch (error) {
    // An already-reviewed patch answers 409/conflict: the store refuses to overwrite a decision.
    message.value = error instanceof Error ? error.message : String(error);
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <div class="locators">
    <section>
      <h2>待审修复补丁 <span class="muted">{{ pending.length }} 条</span></h2>
      <p class="note muted">
        自修复只在唯一候选时更新注册表；≥2 个相似候选即停止并生成候选补丁等人审（docs/PRD.md §8）。
        这个页面就是「人审」那一步。
      </p>
      <p v-if="state.errors.locators" class="error">{{ state.errors.locators }}</p>
      <p v-else-if="!state.registry.heal_patches.length" class="muted">
        还没有修复补丁：gate G1 之前没有真实重定位失败，所以这里应当是空的。
      </p>
      <table v-else>
        <thead>
          <tr><th>补丁</th><th>semantic_id</th><th>建议 chain</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="patch in [...pending, ...reviewed]" :key="patch.patch_id">
            <td class="mono">{{ patch.patch_id }}</td>
            <td class="mono">{{ patch.semantic_id }}</td>
            <td class="mono small">{{ strategies(patch.proposed_chain) }}</td>
            <td>
              <span :class="patch.status === 'pending' ? 'warn' : patch.status === 'approved' ? 'yes' : 'no'">
                {{ patch.status }}
              </span>
              <span v-if="patch.reviewed_by" class="muted small"> · {{ patch.reviewed_by }}</span>
            </td>
            <td>
              <template v-if="patch.status === 'pending'">
                <button :disabled="busy === patch.patch_id" @click="decide(patch, 'approved')">通过</button>
                <button :disabled="busy === patch.patch_id" @click="decide(patch, 'rejected')">驳回</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="message" class="result">{{ message }}</p>
    </section>

    <section>
      <h2>定位器注册表 <span class="muted">{{ state.registry.locators.length }} 条</span></h2>
      <p class="note muted">
        chain 按顺序尝试，每次动作前重新定位；坐标不跨执行复用（docs/framework.md）。
      </p>
      <table>
        <thead>
          <tr><th>semantic_id</th><th>版本</th><th>chain</th><th>后置条件</th><th>最近修复</th></tr>
        </thead>
        <tbody>
          <tr v-for="locator in state.registry.locators" :key="`${locator.semantic_id}-${locator.app_version}`">
            <td class="mono">
              {{ locator.semantic_id }}
              <span v-if="bySemantic.get(locator.semantic_id)?.length" class="warn small">
                （补丁 {{ bySemantic.get(locator.semantic_id)?.length }}）
              </span>
            </td>
            <td class="mono small">{{ locator.app_version }}</td>
            <td class="mono small">{{ strategies(chain(locator)) }}</td>
            <td class="small">{{ locator.verification || "—" }}</td>
            <td class="small">{{ locator.healed_at ?? "未修复" }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.locators { display: flex; flex-direction: column; gap: 22px; }
h2 { font-size: 15px; margin: 0 0 4px; }
.note { font-size: 12px; margin: 0 0 8px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 500; }
td button { margin-right: 6px; }
.small { font-size: 11px; }
.yes { color: var(--ok); }
.no { color: var(--muted); }
.warn { color: var(--warn); }
.result { font-size: 12px; color: var(--info); }
</style>

# A → B 交接说明（G1 合并 + F10 适配器修复）

2026-11-18，A 线（feat/a-perception）。代码侧已收尾，本说明给 B 线控制面合并与适配器修复提供可直接落地的要点。所有引用均在本分支可复现；原始实测证据在 gitignored `var/experiments/`。

## 0. 状态速览

A 线已落地（均增量，冻结默认路径未改）：
- G1 集成 `8a808f6`：`packages/focusguard/evidence_bridge.py`（差异3 证据落库）、`packages/execution/integrated.py`（端到端 IntegratedExecutor）、`packages/router_engine.py::send_task_routed`（chat-only 可选入口）。
- S4-a `affa897`：`packages/semantic/heal_store.py::recording_patch_writer`（heal 提案→`store.heal_patches` pending 行，供 heal-review REST）。
- 真实 agent live `4b999bc`：`examples/agent_live_demo.py` + `src/probe/experiment_approval_switch.py`。
- 文档 `be894e0`：design §11.4 已记录 F10 根因与真实 agent live 证据。

非 live 套件 334 通过 / 1 跳过。能力表已冻结（`capabilities.draft.yaml` status=frozen，send_task 发送点击实测 **none**）；api.md 已按 R2a 扩展 `state/risk/interference_observed`。R1–R6 负责人 2026-11-17 签批（你签即算 approve，B 由用户同步）。

## 1. F10 适配器修复（B 线，最高优先）

**症状**：冻结 `packages/adapters/trae/adapter.py::_force_manual_approval` 在本机 build（Trae 1.107.1 / 组件 3.6.13）恒返 `unverified:no_menu`，即便审批已是手动。导致 `send_task(mode="agent")` 内部审批前置失败 → `approval_required`，agent live 走不通。

**根因（实测 run `20261118T073742Z`）**：
1. 选择器错：审批弹层真实容器是 `[class*=permissionModePopover]`（`popover role=dialog`）+ `[class*=permissionModeItem-]` 行，**不是** `.popup-menu` / `.popup-menu-item`（后者在审批面不存在）。
2. 选项名读取：`permissionModeItemName` 的 `innerText` 为空，须用 `textContent`。四个选项：手动审批 / 自动审批 / 完全访问 / 自定义。
3. 点击方式：可信 `Input.dispatchMouseEvent` 点击 trigger **能打开**弹层；但用可信坐标点选项行**只关闭弹层、不选中**。选项选中须 **JS `row.click()`**（行容器 = Name  span 向上找到 class 匹配 `/permissionModeItem-/` 且不含 Name/Icon/Desc/Text 的祖先）。

**可行序列（已在 demo 验证切到手动审批）**：
```
读 trigger 标签（button[aria-label='手动审批'] || button[aria-label='自动审批'] || [class*=permissionModeTrigger]，取 aria-label||textContent）
若含 手动/manual → return 'manual'
若无 trigger → 'absent'
否则：可信点击 trigger 中心开弹层 → sleep 0.5
  在 permissionModePopover 内找 Name.textContent==='手动审批' 的行容器 → row.click() → sleep 0.8
  读回标签：含 手动 → 'manual'，否则 'unverified:<label>'
```

**模式菜单相反（勿改错）**：`_ensure_chat_mode` 的 `.popup-menu` 经 JS `btn.click()` 打开，**Agent 叶子须可信点击**选中——冻结模式路径本就正确，**不要**改成 JS click。

**安全约束（务必保留）**：
- 绝不选「完全访问」（full access）。
- 行文本精确匹配 `手动审批`，不点 wrapper 节点。
- 仍 fail-closed：切不到手动就返回 unverified，agent 路径据此拒绝（原则 7）。
- 步骤2 行为变更：把「静默跳过」改为显式 `unverified:approval_mode`，让上层可区分（不再静默）。

**参考实现**：`examples/agent_live_demo.py::DemoAdapter._force_manual_approval`（仅子类覆写，可以直接收敛进冻结适配器）。守护测试见 `tests/test_agent_live_demo_guards.py`。

**落地结果（B 线，2026-11-19）**：序列已收敛，演示子类那份副本删除，两条路径共用 `states.py` 的常量与三段 JS。

| A 线要点 | 落点 |
|----|----|
| 弹层容器 `[class*=permissionModePopover]` + 行 `[class*=permissionModeItem-]`，不是 `.popup-menu` | `states.APPROVAL_POPOVER/APPROVAL_OPTION_ROW`；`cdp_direct._force_manual_approval` 重写，找不到的 `.popup-menu` 版本已消失 |
| 可信点击开弹层、JS `row.click()` 选中 | `perception.cdp.CDPChannel.click_at()`（公共 API）→ `states.approval_option_click_js()`；固定 sleep 换成带截止时间的轮询 |
| 用 `textContent` 精确匹配 `手动审批`，不点 wrapper | `approval_option_click_js()` 内 Name→行容器上溯 ≤6 层并跳过 `Name\|Icon\|Desc\|Text`；同名两行按冲突拒（`unverified:ambiguous_option`） |
| 绝不选「完全访问」 | `states.is_allowed_approval_target()` 只放行 `手动审批`，模拟通道在触达 DOM 之前抛错 |
| fail-closed：切不到手动就 unverified | `approval_mode_read` 的 outcome 词表不变，新增 `reason`（`gate_refused`/`option_not_offered`/`no_change`/`label_unreadable`） |

B 侧的一处结构调整：控制面里这一步的门禁动作从 `click` 改成 **`select`**（点开弹层算选择的一部分），
所以审批 token 的 scope 是 `{semantic_ids: ["trae.chat.approval_mode"], actions: ["select"]}`。
Dashboard 按 pending 请求原样授予 scope，无需改动；`examples/handoff_demo.py::approve_forcing_manual` 已同步。
`trae.chat.approval_mode` 的链路仍只有触发器两条（`locators.yaml` 冻结），弹层升成 semantic_id 需双人 approve。

## 2. G1 合并接线清单（B 控制面）

A 线把集成层做成注入式，B 合并时按以下接线把 routed 管线变成**实际默认**（替换冻结 engine/MCP/Dashboard 默认路径，需双人 approve）：

1. **crosswalk（R4b，已批准）**：`packages/routing/operation_names.py`
   - `capability_key("trae.send_task") -> ("trae","send_task")`；`engine_method("trae","get_task_status") -> "get_status"`。
   - MCP 分发用冻结 TOOL_SPECS 名（`trae.get_status`/`trae.read_result`），路由查表用能力表语义名（`get_task_status`/`read_task_result`），经此双向映射对齐，**不改冻结规格、不改能力表键**。

2. **IntegratedExecutor 接线**：`packages/execution/integrated.py`
   - `IntegratedExecutor(guard, store, window_id, consume_approval, max_attempts=3)`。
   - `operation(channel) -> (verified: bool, error: str|None)`：把各通道执行器（UIA/APP_PROTOCOL/OCR…）包成此签名；内部已做 FocusGuard 包裹 + 四态 classify + 原则6 重试 + 证据落库 + R2a 信封。
   - `consume_approval`：接 `store.consume_approval(token, semantic_id, action)`（真实一次性令牌）。高影响无令牌 → 路由本身拒选通道（`no_executable_channel`）；缺消费器 fail-closed。
   - 返回 `(RoutedOutcome, ExtendedEnvelope|None)`；信封 `.to_dict()` 即 api.md R2a 形态（含 `before/after_snapshot_id`、`evidence: list[str]`）。

3. **证据落库（差异3）**：`packages/focusguard/evidence_bridge.py::to_api_envelope(result, window_id, store)` 已把内联 FocusSnapshot 经 `store.add_snapshot` 落库注入 id。B 的 Dashboard/SSE 直接消费这些 snapshot id。

4. **heal-review 闭环（S4-a）**：`recording_patch_writer(cache, store)` 作为 Resolver 的 `patch_writer`，heal 提案即落 `heal_patches` pending 行；desktop-agent `POST /locators/{semantic_id}/heal-review` → `store.review_heal_patch` 已能审真实行。

5. **冻结边界（勿动默认 until 合并 approve）**：`semantic/element.py`、`mcp_gateway/server.py` Engine Protocol/TOOL_SPECS、`execution/actions.py`、`execution/safety.py`、`locators.yaml`、`schema.sql`。`engine.send_task_routed` 是增量验证面；正式替换 `send_task`/`perform_action` 默认在 G1 合并时做。

## 3. 真实 agent live 证据（隔离 demo）

- 工作区 `<隔离演示仓库>`（本机路径不入库）（git baseline `d25fb46`，agent 产出 `8275bc7`）。
- run `20261118T074629Z`，task `task_69f57b6a5f03`：真实 Trae agent 实改 `index.html`（+6/-1 显示/隐藏切换），独立 Verifier 确认仅改 index.html + `node --test` 3/3，链 submitted→verified。agent 的 npm-test 审批提示为 untrusted 数据未执行（原则7）。
- 运行器 `examples/agent_live_demo.py`：`--authorize-live-agent` 拒绝门、真实项目 basename 硬阻断、git 前置、按 demo 标题精确选 CDP 页（无回退）、人工手动审批前置。**agent live 仅限隔离 demo，绝不碰真实项目。**
- 模拟 handoff `examples/handoff_demo.py` 是明确标注的 SimulatedAgentEngine，**不得冒充真实 verified**。

## 4. live 测试钉窗（小修）

`tests/test_live_heal.py` / `test_live_locate.py` 取首个 Trae CDP 页面（`trae[0]`）。demo 窗口开着时会误指向 demo 而失败。建议 live 测试按目标窗口标题钉住（如 Agui），或在多 Trae 窗口时显式选择。非 live 套件不受影响。

## 5. 门清单

- **G1（11/20）**：A 集成 + B 控制面合并、crosswalk/通道绑定、冻结默认替换、双人 approve。A 侧已就绪。
- **G2–G4（11/23–11/27）**：经真实 MCP 网关 + Dashboard 的端到端 live（审批 REST、SSE 回放、heal-review UI）；微信负例（OCR 仅定位）演示。
- **G5（11/30）**：公开发布（sites）+ 录屏 + 最终文档。前置 G1–G4 live 全通；发布前确认站点不含本地执行器/调试端口/证据目录。
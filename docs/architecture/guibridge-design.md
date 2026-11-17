# GUIBridge 架构设计（独立研发任务书对齐版）

状态：Phase 0 草案（2026-11-17）
契约状态：本文件中的 Router / FocusGuard / ActionResult 接口为**草案**，按 D7 需 B 线 approve 后才冻结；`element.py`、Engine Protocol、`locators.yaml`、`schema.sql`、`api.md` 继续冻结，未获双人批准不得变更。

## 1. 定位与边界

GUIBridge 是面向 Windows 的通用桌面应用语义控制与跨 Agent 协作系统。本项目独立实现，不复制、移植、翻译或改写 vercel-labs/agent-desktop 的源代码，也不将其作为运行时依赖。参考范围限于 Windows/MCP/CDP 等公开标准与文档。

本文件描述三项核心能力：

- A. Capability-Aware Execution Router（能力感知执行路由）
- B. FocusGuard（后台操作干扰检测）
- C. AI IDE 语义适配器（当前目标：Trae）

## 2. 设计原则

1. Windows 优先，本期不支持 macOS / Linux。
2. 原生应用优先系统语义接口（UIA），而不是模拟鼠标。
3. UIA 不可用时允许 OCR / 视觉识别，但不把 OCR 定位能力误认为后台输入能力。
4. 每个执行通道必须声明焦点干扰风险。
5. 所有任务返回结构化执行结果。
6. 无法确认是否成功的非幂等操作，禁止自动重复执行。
7. 高影响操作必须经过用户审批。
8. 不绕过系统安全桌面、权限边界或应用安全机制。

## 3. 核心能力 A：Capability-Aware Execution Router

### 3.1 通道模型

| 通道 | 说明 | 典型前提 | 声明干扰风险 |
|---|---|---|---|
| `OFFICIAL_API` | 应用官方 API / SDK | 凭据、服务可用 | `NONE` |
| `CLI` | 应用官方 CLI | 版本支持、可非交互 | `NONE` 或 `LOGICAL_ONLY` |
| `UIA` | Windows UI Automation pattern 调用 | 控件暴露 Invoke/Value/Toggle 等 pattern | 不移动物理输入；焦点风险需实测（见 3.5，本机靶应用为 `FOCUS_SWITCH`） |
| `APP_PROTOCOL` | 应用允许的专用协议，如 Electron CDP（仅 loopback） | 应用可托管启动/已开调试端口 | `NONE` |
| `OCR_VISION` | 截图识别定位 | 目标可见 | 仅定位；若配合输入则继承输入风险 |
| `FOREGROUND_INPUT` | SendInput / 物理级模拟 | 目标前台、可用输入 | `PHYSICAL_INPUT` |
| `VM_ISOLATED` | 虚拟机/第二会话内执行 | 隔离环境 | `NONE`（对宿主） |

### 3.2 干扰风险等级

`NONE` < `LOGICAL_ONLY` < `FOCUS_SWITCH` < `PHYSICAL_INPUT`；`UNKNOWN` 视为不可用，除非用户显式批准。

### 3.3 干扰策略

| 策略 | 无审批允许 | 需审批 | 拒绝 |
|---|---|---|---|
| `STRICT_NO_INTERFERENCE` | `NONE`、`LOGICAL_ONLY` | `FOCUS_SWITCH`、`PHYSICAL_INPUT` | `UNKNOWN` |
| `BALANCED` | `NONE`、`LOGICAL_ONLY`、`FOCUS_SWITCH` | `PHYSICAL_INPUT` | `UNKNOWN` |
| `FOREGROUND_ALLOWED` | 全部已知风险（高影响动作仍走 SafetyGate 审批） | — | `UNKNOWN` |

严格无干扰模式禁止未经批准的焦点切换、物理鼠标移动和键盘注入。策略只决定“通道是否可选”，高影响操作的审批由既有 `SafetyGate` 独立执行，两者叠加而非互相替代。**草案路由层另内置影响维度**（见 3.6）：`OperationImpact.HIGH` 的操作即便落在 `NONE` 风险通道，未经批准也被 `is_allowed` 拒绝、`operation_requires_approval` 返回 True，使原则 7 在新契约层即可强制执行，而不只依赖冻结的 `SafetyGate`。

### 3.4 路由算法（Phase 1 使用静态能力表）

输入：`Capability`（含 app 与 operation，来自真实 scan 的能力表）、`policy`、`approved`。
输出：`ChannelDecision`。

1. 取 `cap.channels` 中为真的通道。
2. 按风险等级升序、同风险按通道优先级排序。
3. 按策略过滤；需审批且未批准则跳过。
4. 返回首个可用通道及其 fallbacks；无可用通道返回 `channel=None` 并给出原因（含负例证据，如“微信 4.x UIA 无节点”）。

Phase 1 不做动态学习或在线探测；能力表由 `src/probe/run_experiments.py` 的 E5 扫描输出并人工复核，落为草案数据文件 `packages/routing/capabilities.draft.yaml`，由 `packages/routing/capability_table.py` 的 `load_capability_table()` 加载为 `Capability` 对象供 `StaticRouter` 消费。风险值取自实测（原生 UIA=`focus_switch`）；未用 FocusGuard 实测的通道（如 Trae CDP）保持 `unknown`，不得假设为 `logical_only`。

### 3.5 Phase 1 实测修正（2026-11-17）

`docs/experiments/background-control.md` 的 E1b 对受控 Win32 靶应用做了 3 种 pattern × 3 个后台窗口的隔离试验：

- 9/9 效果回读成功，9/9 光标位移为 0；
- 9/9 前台在动作窗口内切换到目标，9/9 未检测到外部输入；
- 因此该应用的 UIA 风险应声明为 `FOCUS_SWITCH`，不能默认 `LOGICAL_ONLY`。

设计修正：能力表按“应用 × 操作 × 控件 × 目标前后台状态”实测风险；`STRICT_NO_INTERFERENCE` 下未批准的 UIA 焦点切换仍应被拒。UIA 的“光标零位移”与“无焦点干扰”必须分开报告，不得用前者替代后者。

增补 run `20261117T090104Z` 的 E1c（前台起步对照）进一步表明：目标已在前台时，9/9 UIA 动作仍引发瞬时焦点切换（切走再切回，`external_input=false`），其中 3 次短到 2 ms 轮询漏记、由 `EVENT_SYSTEM_FOREGROUND` 事件钩子捕获。因此“前台起步可视为无焦点干扰”的假设不成立，风险声明必须覆盖前后台两种状态，且 FocusGuard 需以事件钩子补捉瞬时切换。

### 3.6 操作影响维度（原则 7，草案）

干扰风险描述“通道对宿主焦点/输入的影响”，与“操作本身的影响”正交。一个 `NONE` 风险的官方 API 删除调用、或一次真实消息发送，仍可能是高影响、非幂等操作。为此 `Capability` 增加操作级元数据：

- `impact: OperationImpact`（`LOW`/`HIGH`，默认 `LOW`）：`HIGH` 表示改状态/非幂等/破坏性/发送真实消息，必须经用户审批；`LOW` 表示只读或可安全回退。
- `idempotent: bool`（默认 `True`）：供重试策略（4.2、原则 6）判定是否允许自动重试。

强制点：`policy.is_allowed(policy, risk, approved, impact)` 在 `impact=HIGH` 且未批准时直接拒绝（与 `UNKNOWN` 同级硬门），`operation_requires_approval(policy, risk, impact)` 对 `HIGH` 恒返回 True；`StaticRouter` 两处分支均改用该组合判定。因此高影响操作不会因通道无干扰而被自动放行。草案能力表已标注：`trae.send_task`、`wechat.send_message` 为 `high`/非幂等；只读接口与受控靶应用操作为 `low`。含单测 `tests/test_impact_approval.py`（25 例）。该维度为草案，Phase 2 接入执行器时与冻结 `SafetyGate` 叠加生效。

## 4. 核心能力 B：FocusGuard

### 4.1 监测信号

- 前台窗口 HWND（动作前后 + `EVENT_SYSTEM_FOREGROUND` 事件）。
- 用户鼠标位置（动作前后采样 + 动作窗口内轨迹）。
- 系统最后输入年龄（`GetLastInputInfo`），用于标记窗口内是否存在外部输入，避免把用户操作归因给自动化动作。
- 目标窗口是否处于激活状态。
- 自动化动作是否引起非预期焦点切换。
- 目标操作是否真正生效（控件状态 / 文本 / 业务后置条件）。

### 4.2 四态结果

| 状态 | 含义 |
|---|---|
| `SUCCESS_NO_INTERFERENCE_OBSERVED` | 操作成功，且监测窗口内未观察到干扰 |
| `SUCCESS_WITH_INTERFERENCE` | 操作成功，但观察到焦点切换/光标移动等干扰 |
| `FAILED` | 确认失败（抛出错误 / pattern 不可用等明确错误） |
| `UNCONFIRMED` | 动作已执行、无错误，但未能正面确认成功；不得据此断言“确定失败”（非幂等操作禁止自动重试） |

**表述纪律**：`SUCCESS_NO_INTERFERENCE_OBSERVED` 只表示“未观察到”，不能表述为“绝对无干扰”。文档与 UI 必须保留该限定。

**分类映射（`classify()`）**：`error` 非空 → `FAILED`；`verified=True` → 两种成功态（按通道与干扰信号细分）；`verified=False` 且无 `error` → `UNCONFIRMED`。早期实现把“未确认成功”一律归 `FAILED`，会使 `UNCONFIRMED` 不可达、原则 6 的未确认分支形同虚设，且把“未确认”误报为“确定失败”；现已修正为保守映射（缺正面确认 ≠ 确定失败）。含单测 `tests/test_phase1_classification.py`。另：`src/probe/uia_exec.py` 的 `ActionResult.risk` 曾硬编码 `LOGICAL_ONLY`，与本机靶应用实测 `FOCUS_SWITCH`（E1b/E1c）矛盾，已改为 `FOCUS_SWITCH`；`run_experiments.action_record` 的默认风险同样由 `LOGICAL_ONLY` 改为 `FOCUS_SWITCH`（与其默认 UIA 通道一致）。修正经 run `20261117T100205Z` 端到端实测确认（3/3 `focus_switch`）；历史 run 为冻结证据不追溯改写，后续复跑按实测风险报告。

**重试约束落地**：原则 6（非幂等未确认操作禁止自动重试）由草案 `packages/focusguard/retry_policy.py` 的 `decide_retry(state, idempotent, attempts, max_attempts)` 强制：`UNCONFIRMED`/`FAILED` 且非幂等一律 `allow_retry=False` 且 `requires_approval=True`；幂等操作仅在预算内可重试，预算耗尽转人工审批；两种成功态不重试。该约束在 Phase 2 接入执行器前为独立草案，含单测 `tests/test_retry_policy.py`（11 例）。

### 4.3 采样限制

FocusGuard 采用动作前后快照 + 2 ms 前台/光标采样 + `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` 事件钩子（独立消息泵线程）。纯轮询不保证捕获两次采样之间的瞬时切换：增补 run 的 E1c 中轮询漏记 3 次瞬时切换，事件钩子 9/9 全部捕获。E2 停留曲线在实测约 57–138 ms 的注入切换上，轮询与钩子均 9/9 检出、0/3 误报。后续 `src/probe/dwell_limit.py` 用更快注入（线程输入一次性附着 + 裸 `SetForegroundWindow`）把停留压到毫秒级，0/5/10/20/50 ms 各 5 次共 25/25 轮询与钩子均检出、0 外部输入污染——说明此前 ~57 ms 下限是 `quick_foreground` 开销而非 FocusGuard 极限。钩子另采集系统 `event_time`（`FocusRun.hook_event_times` + `hook_dwell_ms()`）做精确计时：最短可解析真实停留 15 ms（run `20261117T093513Z`），`time.time()` 的 8.9/5.1 ms 含分发延迟不作下限；`event_time` 为 1 ms 分辨率，同 tick 事件无法解析（1 个 None）。**<2 ms 的切换仍未实证覆盖**（2 ms 采样盲区 + 1 ms 计时分辨率）。大样本复核（`src/probe/focusguard_reliability.py`，run `20261117T093120Z`）：30 静默负例误报 0/30、15 注入正例（~100 ms）检出 15/15（轮询与钩子均 15/15），强化 E2 小样本结论。`GetLastInputInfo` 只能标记窗口内“存在输入事件”，不能区分输入来源；Physical Input 通道自身注入的输入需单独标记为动作注入。

## 5. 核心能力 C：AI IDE 语义适配器（Trae）

### 5.1 通道选择依据

`src/probe/PROBE_REPORT.md` 实测（F1–F12）：

- Trae 3.6.13 的 UIA 树默认仅 17 个框架级节点；加 `--force-renderer-accessibility` 后 62 个节点，但聊天输入框/发送按钮仍不可见（F1/F2）。
- CDP 可读取完整聊天 DOM 语义并完成提交→状态→读回闭环（F3/F6/F12）。
- 审批模式触发器无法通过 CDP 打开菜单，Agent 模式必须由人工预先切换为手动审批（F10）。

结论：Trae 属于 Electron 目标，主通道为 `APP_PROTOCOL`（loopback CDP），而非 UIA。这符合任务书“应用允许的专用协议”通道，不违反“原生优先系统语义接口”。

### 5.2 业务接口契约

| 接口 | 前置条件 | 执行步骤 | 后置条件 | 验证证据 |
|---|---|---|---|---|
| `send_task` | 目标窗口白名单；chat 模式已确认；审批为手动或显式批准；项目路径在允许范围 | 定位 composer → 写入文本 → 点击发送 | 返回 `task_id`，状态 `submitted` | composer 清空、发送按钮状态、运行态信号 |
| `get_task_status` | 任务存在 | 读取运行态/审批/回复文本 | 状态 `submitted/running/claimed_done/failed/unknown` | 状态信号 + 回复长度/内容；unknown 抑制窗口 180s |
| `read_task_result` | 状态为 `claimed_done` | 读取会话文本 | 返回文本并标记 `untrusted=true` | DOM 读回快照；回复内容永不作为指令执行 |
| `verify_code_changes` | 隔离 worktree；`allowed_files`；`test_command` | 采集 git 变更 → 运行测试 → 校验范围 | `verified` / `failed` | `git status --porcelain` 范围 + 测试退出码 + 证据 ID |

现有实现：`packages/adapters/trae/adapter.py`、`packages/execution/verifier.py`、`packages/engine.py`。Phase 2 将 `verify_code_changes` 正式接入适配器与 MCP 表面。

焦点干扰实测（run `20261117T092712Z`，`src/probe/trae_cdp_focus.py`）：只读 CDP 路径（`get_task_status`/`read_task_result`）经 FocusGuard 包裹 5/5 光标 0、无前台切换、无外部输入，实测风险 `none`，已写入能力表草案。`send_task` 的发送点击未覆盖，风险仍 `unknown`，需授权 live 测量；不得由只读 `none` 外推。

## 6. 数据契约（草案，待 B 线 approve）

```python
class Channel(str, Enum):
    OFFICIAL_API; CLI; UIA; APP_PROTOCOL; OCR_VISION; FOREGROUND_INPUT; VM_ISOLATED

class InterferenceRisk(str, Enum):
    NONE; LOGICAL_ONLY; FOCUS_SWITCH; PHYSICAL_INPUT; UNKNOWN

class InterferencePolicy(str, Enum):
    STRICT_NO_INTERFERENCE; BALANCED; FOREGROUND_ALLOWED

@dataclass(frozen=True)
class Capability:
    app: str
    operation: str
    channels: dict[Channel, bool]
    risk: dict[Channel, InterferenceRisk]
    preconditions: dict[Channel, list[str]]
    unsupported_reason: str | None

@dataclass
class ChannelDecision:
    channel: Channel | None
    risk: InterferenceRisk
    requires_approval: bool
    fallbacks: list[Channel]
    reason: str

@dataclass
class FocusSnapshot:
    foreground_hwnd: int
    cursor_xy: tuple[int, int]
    target_active: bool
    ts: float

class ResultState(str, Enum):
    SUCCESS_NO_INTERFERENCE_OBSERVED
    SUCCESS_WITH_INTERFERENCE
    FAILED
    UNCONFIRMED

@dataclass
class ActionResult:
    state: ResultState
    channel: Channel
    risk: InterferenceRisk
    effect_verified: bool
    evidence: dict
    focus_before: FocusSnapshot
    focus_after: FocusSnapshot
    unexpected_focus_switch: bool
    task_id: str | None
```

代码草案：`packages/routing/`、`packages/focusguard/`、`packages/execution/uia_channel.py`。所有模块在 Phase 1 前不接入 `engine` / `mcp_gateway` / Dashboard。

## 7. 与现有原型资产的关系

| 阶段 | 现有资产 | Phase 1 处理 |
|---|---|---|
| S0 | `src/probe/` 探针与 F1–F12 | 复用；Trae 能力证据重组进实验文档 |
| S1 | `packages/perception/*`、`packages/semantic/*` | 复用；UIA 通道扩展执行能力（Phase 1） |
| S2 | `adapters/trae`、`execution`、`events`、`engine`、`mcp_gateway` | 冻结，不改接口；Phase 2 整合 Router/FocusGuard |
| S3 | `verifier`、`examples/handoff_demo.py` | 复用；Phase 2 接入 Trae 适配器 |
| S4 | 自修复 + Dashboard | 冻结；Dashboard 不作为 Phase 1 优先项 |
| S5 | A/B/C benchmark | 复用方法；Phase 1 新增原生 UIA/干扰实验 |

## 8. 安全边界

- CDP 仅绑定 loopback，随机端口，进程退出即关闭；不开放远程调试。
- Agent 模式必须由人工设置为手动审批；无法自动设置时返回 `unverified:*` 并阻断。
- 目标窗口白名单；高影响动作需一次性审批 token。
- 聊天/文档文本一律视为不可信数据，`read_result` 返回值不得作为指令执行。
- 探针截图/dump 仅本地保存，不入库、不上传公开站点。
- 不绕过 UAC/安全桌面，不注入系统进程，不安装内核驱动。

## 9. 验收映射

| 任务书验收项 | Phase 1 实验 | 证据 |
|---|---|---|
| 至少一个应用支持不移动物理鼠标的语义操作 | E1（原生 UIA）+ 已有 Trae CDP | `var/experiments/*.json` + Trae 探针 |
| 记录焦点变化事件 | E2 | FocusGuard 事件日志 |
| 检测目标控件操作是否成功 | E1/E3 | 状态回读 + 四态结果 |
| 明确识别不支持后台操作 | E5（含微信 4.x / Trae UIA 负例）+ 自绘靶应用负例（run `20261117T102927Z`） | capability scan 输出 |
| Trae 实际能力有测试证据 | E6（只读复跑 + 授权 live 无害消息） | `src/probe/PROBE_REPORT.md` 增补；Chat 模式读回 `OK`、工作区零变更 |
| 所有实验可重复运行 | `src/probe/run_experiments.py` | 固定环境记录 + 原始 JSON |

## 10. 开放问题

1. ~~ctypes Win32 标准控件经 MSAA→UIA 桥的 pattern 可用性需 E1 实测~~ 已实测：Invoke/Value/Toggle/Text 均可用（E1/E1b/E1c），无需切换备选靶应用。
2. ~~FocusGuard 漏检率与采样频率的关系需量化~~ 已部分量化：事件钩子补捉轮询漏掉的瞬时切换（E1c）；`dwell_limit.py` 快注入实测停留低至约 8.9 ms，25/25 轮询+钩子检出、0 污染；<2 ms 理论盲区仍待量化。
3. Trae 版本升级后的选择器漂移由既有 heal 流程覆盖，需 Phase 2 复验。
4. 新契约需 B 线 approve 后才能从“草案”转为冻结（见第 11 节评审包）。
5. **外部输入下的效果归因**：`classify()` 目前对 `verified=True` 判成功态，即便 `external_input_during_window=True`。对不注入输入的通道（UIA/APP_PROTOCOL），窗口内出现外部输入意味着观测到的效果可能由用户而非动作造成，效果归因存疑——是否应降级为 `UNCONFIRMED`？对 `FOREGROUND_INPUT` 则需先区分“动作自身注入”与“真正外部输入”（当前 `FocusRun` 仅一个布尔标记，未分离）。实验层已用“污染运行弃用并保留原文件”规避，但契约层是否内置降级待定，需 B 线评审决定，避免草率改动误伤物理输入通道的自注入情形。

## 11. 契约评审包（待 B 线 approve）

本节汇总 Phase 1 形成的新契约草案与实测依据，供 B 线评审。**评审通过前不得接入冻结的 `engine` / `mcp_gateway` / Dashboard，不得变更旧契约（`element.py`、Engine Protocol、`locators.yaml`、`schema.sql`、`api.md`）。** G0 尚未正式通过。

### 11.1 待评审草案清单

| 草案 | 位置 | 状态 |
|---|---|---|
| `Channel` / `InterferenceRisk` / 策略过滤 | `packages/routing/capability.py`、第 3、6 节 | 草案 |
| `FocusSnapshot` / `FocusRun` / `FocusGuard` Protocol | `packages/focusguard/monitor.py`、`outcome.py`、第 4 节 | 草案 |
| 四态分类 `classify()` | `packages/focusguard/classify.py`、第 4.2 节 | 草案（含单测） |
| UIA 执行通道与风险声明 | `src/probe/uia_exec.py`、第 3.5 节 | 草案 |
| UIA 形式化通道草案实现（注入式，未接入） | `packages/execution/uia_channel.py`、第 11.4 节差异 8 | 草案（含单测） |
| Trae 四接口契约 | 第 5.2 节 | 草案（Phase 2 正式接入） |
| 实测能力表 + 加载器 | `packages/routing/capabilities.draft.yaml`、`capability_table.py` | 草案（含单测） |
| 重试策略（原则 6 落地） | `packages/focusguard/retry_policy.py`、第 4.2 节 | 草案（含单测） |
| 操作影响维度 + 审批门（原则 7 落地） | `packages/routing/capability.py`、`policy.py`、`router.py`、第 3.6 节 | 草案（含单测） |
| 四态→冻结信封桥接（集成候选） | `packages/focusguard/legacy_bridge.py`、第 11.4 节 | 草案（含单测，未接入冻结模块） |

### 11.2 B 线 approve 检查项

- [ ] 确认 UIA 风险按“应用 × 操作 × 控件 × 前后台状态”实测，本机靶应用声明为 `FOCUS_SWITCH`，不接受 `UIA=LOGICAL_ONLY` 默认值。
- [ ] 确认 E1c 前台起步仍存在瞬时焦点切换的结论，认可以事件钩子作为 FocusGuard 必备信号（而非可选）。
- [ ] 确认四态语义：`SUCCESS_NO_INTERFERENCE_OBSERVED` 仅表示“未观察到”；Physical Input 验证成功一律 `SUCCESS_WITH_INTERFERENCE`；非幂等未确认操作禁止自动重试。
- [ ] 确认 `external_input_during_window` 仅标记“窗口内有输入事件”，不用于单独判定干扰；污染运行须弃用并保留原文件。
- [ ] 确认 E2 停留曲线仅覆盖 57–138 ms，<50 ms 漏检率未量化，不得外推为“任意瞬时切换可检出”。
- [ ] 确认 Trae 主通道为 `APP_PROTOCOL`（loopback CDP），live 证据仅限授权的一次 Chat 无害消息；agent 模式默认手动审批。
- [ ] 确认微信负例（可见窗口仅 4 个 UIA 框架节点）作为“不支持后台语义操作”的证据。
- [ ] 复核 `capabilities.draft.yaml` 各条目的实测风险与证据 run id；确认 Trae 只读接口已实测 `none`（run `20261117T092712Z`），而 `send_task` 发送点击仍 `unknown`（不假设 `logical_only`），并认领授权 live 测量任务。
- [ ] 确认新契约冻结前不接入冻结模块；双人 approve 记录留痕。
- [ ] 确认原则 6 由 `retry_policy.decide_retry` 强制（非幂等 `UNCONFIRMED`/`FAILED` 拒绝自动重试并转人工审批，幂等仅预算内重试），复核 `tests/test_retry_policy.py` 矩阵；Phase 2 执行器接入时须调用该策略而非自行重试。
- [ ] 确认原则 7 由草案路由层 `OperationImpact.HIGH` 审批门强制（高影响操作即便 `NONE` 风险也须批准），复核 `tests/test_impact_approval.py` 与能力表 `impact`/`idempotent` 标注；确认其与冻结 `SafetyGate` 叠加而非替代，`UNKNOWN` 风险即便批准仍不可用。
- [ ] 裁决开放问题 5：外部输入窗口内 `verified=True` 是否对非输入通道降级 `UNCONFIRMED`，以及 `FOREGROUND_INPUT` 自注入与外部输入的分离方案；确认 `classify()` 保守映射（`UNCONFIRMED` 可达）与探针实测 `FOCUS_SWITCH` 风险报告。
- [ ] 评审 11.4 集成就绪性差异：裁决是否扩展 `api.md` 信封以承载四态/风险（否则 `UNCONFIRMED` 在 MCP 边界退化为失败，需双人 approve）；确认审批双门叠加、重试前调 `decide_retry`、操作命名对齐、`UIAExecChannel` 实测回填方案。

### 11.3 实测依据索引

- 基线 run `20261117T082451Z`、增补 run `20261117T090104Z`：`docs/experiments/background-control.md` 第 7、11 节。
- 短停留检测限 run `20261117T091848Z`：`src/probe/dwell_limit.py`，实测停留低至约 8.9 ms、25/25 检出（第 12 节）；精确计时复跑 run `20261117T093513Z` 最短可解析真实停留 15 ms（第 12.1 节）。
- 四态分类单测：`tests/test_phase1_classification.py`（15 例）——含 `error→FAILED`、`verified=False` 无错误→`UNCONFIRMED`（四态可达、保守映射）、`detect_unexpected_focus_switch` 聚合（轮询漏记、仅钩子捕获仍判干扰）与 `hook_dwell_ms` 精确计时（含 32 位回绕、缺失对返回 None）。
- 路由契约单测：`tests/test_phase1_routing.py`（18 例）——锁定“实测 UIA=FOCUS_SWITCH 在 STRICT 下未批准被拒、批准后可用”、风险升序+通道优先级排序、fallback 排除被拒通道、UNKNOWN 永不可用、策略×风险×审批矩阵。对应 11.2 检查项 1、3 已有可执行证据。
- 实测能力表单测：`tests/test_capability_table.py`（8 例）——草案表加载、原生 UIA 实测 focus_switch、BALANCED 选 UIA / STRICT 未批准被拒、微信负例返回原因、自绘负例返回原因（`selfdrawn-test.invoke` 无支持通道）、Trae send_task CDP unknown 不自动放行、Trae 只读接口实测 none 可在 STRICT 放行。
- 自绘靶应用能力扫描 run `20261117T102927Z`：`src/probe/selfdrawn_app.py`（GDI 自绘客户区控件、无子 HWND）+ `src/probe/scan_selfdrawn.py`。自绘窗口 UIA 树 7 节点：`has_edit=false`、`content_button_count=0`，仅 3 个非客户区标题栏按钮（最小化/最大化/关闭，TitleBar 下，属窗口框架 chrome 而非应用内容）；原生标准控件靶应用对照 `has_edit=true`、`content_button_count=1`。结论：自绘应用内容无 UIA 语义，后台语义操作不可用、OCR/视觉仅定位。已落能力表草案 `selfdrawn-test.invoke`（unsupported，含原因与证据）。补齐验收项 4 的第三类应用负例（原生/Electron/自绘）。
- 重试策略单测：`tests/test_retry_policy.py`（11 例）——成功态不重试、非幂等 `UNCONFIRMED`/`FAILED` 拒绝自动重试且 `requires_approval=True`、幂等预算内可重试、预算耗尽转审批、非幂等即便预算有余仍拒绝。对应 11.2 原则 6 检查项的可执行证据。
- 影响审批单测：`tests/test_impact_approval.py`（25 例）——三策略下 `HIGH` 影响 `NONE` 风险未批准被拒/批准可用、`LOW` 影响 `NONE` 风险免审批、`HIGH`+`UNKNOWN` 即便批准仍拒、`operation_requires_approval` 对 `HIGH` 恒真、`StaticRouter` 高影响门控、能力表 `send_task` high/非幂等与只读接口 low/幂等标注。对应 11.2 原则 7 检查项的可执行证据。
- 草案契约组合单测：`tests/test_draft_contract_integration.py`（5 例）——不接入冻结执行器，验证能力表元数据贯通：`send_task` 被路由拒绝（unknown）且非幂等未确认禁重试；只读接口幂等元数据放行重试；原生 invoke 分类 `SUCCESS_WITH_INTERFERENCE` 后不重试、`FAILED` 与 `UNCONFIRMED` 非幂等均禁重试。证明路由→分类→重试三草案契约可组合。
- 能力表完整性守护单测：`tests/test_capability_table_integrity.py`（4 例）——支持通道若为 `unknown` 风险必须有书面测量缺口说明、`logical_only` 必须有实测证据、仅不支持条目必须给原因、每条 `impact`/`idempotent` 可解析。把“不得假设风险/不得伪造数据”纪律落为对真实数据文件的可持续检查。
- 冻结信封桥接单测：`tests/test_legacy_bridge.py`（8 例）——四态→`success`/`verified`/`error_code` 映射、干扰标记与风险透传，并显式锁定 `UNCONFIRMED` 与 `FAILED` 在冻结两态布尔下不可区分（仅保留的 `state` 可分离）。把 11.4 集成差异 1/2 落为可执行候选，未接入冻结模块、未改 `api.md`。
- UIA 形式化通道草案单测：`tests/test_uia_channel.py`（12 例）——fake 注入下 invoke/set_value/toggle 的四态（验证成功+焦点切换→`SUCCESS_WITH_INTERFERENCE`、无干扰→`SUCCESS_NO_INTERFERENCE_OBSERVED`、pattern 不可用/控件缺失/调用抛错→`FAILED`、执行但未回读确认→`UNCONFIRMED`）、实测 `FOCUS_SWITCH` 风险、`read_state` 委托、焦点证据透传、仅光标位移亦判干扰。把 11.4 差异 8 的空壳补为可执行草案，未接入冻结执行器。
- UIA 形式化通道实测验证 run `20261117T102127Z`：`src/probe/verify_uia_channel.py`，以真实适配器（uiautomation pattern + Win32FocusGuard + 靶应用回读）驱动正式 `UiaPatternChannel`，受控靶应用 invoke/set_value/toggle 各一次，3/3 `risk=focus_switch`、`state=success_with_interference`、`effect_verified=True`，与探针 `uia_exec.py` 实测一致——证明形式化草案通道在真实测量下复现四态与实测风险（非仅 fake；原始 JSON 入 gitignored `var/experiments/`）。
- Trae 只读 CDP 焦点实测 run `20261117T092712Z`：`src/probe/trae_cdp_focus.py`，只读路径 5/5 无干扰（第 13 节）。
- FocusGuard 大样本可靠性 run `20261117T093120Z`：`src/probe/focusguard_reliability.py`，误报 0/30、检出 15/15（第 14 节）。
- 分类/风险修正实测验证 run `20261117T100205Z`：`src/probe/verify_classify.py`，受控靶应用 invoke/set_value/toggle 各一次，3/3 `risk=focus_switch`（修正后非 `LOGICAL_ONLY`）、`state=success_with_interference`、`effect_verified=True`，端到端确认四态分类与实测风险报告（原始 JSON 入 gitignored `var/experiments/`）。
- 草案契约链实测组合 run `20261117T101352Z`：`src/probe/verify_contract_chain.py`，受控靶应用三操作各跑完整草案链（能力表→`StaticRouter`→真实 UIA 执行→四态分类→`decide_retry`→`to_legacy_envelope`）。3/3：STRICT 未批准拒绝（`channel=None`）、STRICT 批准与 BALANCED 均选 UIA、实测 `risk=focus_switch`、`success_with_interference`、成功态不重试、冻结信封 `success=True`。把 11.3 的合成组合单测（`test_draft_contract_integration.py`）落到真实测量数据，证明路由→分类→重试→桥接四草案契约在实测下可组合（不接入冻结执行器；原始 JSON 入 gitignored `var/experiments/`）。
- 代码提交：`4665ab8`（P0 实验改进）。

### 11.4 Phase 2 集成就绪性与契约差异（只读审计，未改冻结模块）

对冻结契约（`semantic/element.py`、`mcp_gateway/server.py` 的 Engine Protocol/TOOL_SPECS、`execution/actions.py`、`execution/safety.py`）与新草案层做只读比对，列出 Phase 2 接入前必须裁决/桥接的差异。**本节仅为评审输入，不代表已接入；G0 未过、冻结模块未改。**

1. **两套 `ActionResult` 不兼容**：冻结 `semantic.element.ActionResult` 为两态布尔（`success`/`verified` + `before/after_snapshot_id` + `error_code` + `evidence: list[str]`）；草案 `focusguard.outcome.ActionResult` 为四态（`state` + `channel` + `risk` + `effect_verified` + `evidence: dict` + 内联 `FocusSnapshot`）。桥接需把四态映射回冻结信封，但**冻结 `success` 布尔无法区分 `FAILED` 与 `UNCONFIRMED`**——两者都落 `success=False/verified=False`，原则 6 的“未确认”语义在 MCP 边界丢失。裁决项：是否扩展 `api.md` 信封增加 `state`/`risk` 字段（属契约改动，需双人 approve），否则 UNCONFIRMED 只能在引擎内部保留、对外退化为失败。候选桥接已落为草案 `packages/focusguard/legacy_bridge.py`（`to_legacy_envelope`，含 8 例单测显式锁定该退化），未接入冻结模块、未引入新错误码，供评审评估。
2. **四态→冻结映射（建议）**：`SUCCESS_NO_INTERFERENCE_OBSERVED`/`SUCCESS_WITH_INTERFERENCE` → `success=True, verified=True`（干扰信息需新信封字段承载）；`FAILED` → `success=False, error_code` 置位；`UNCONFIRMED` → `success=False, verified=False` 且**必须**另带 `state=unconfirmed` 标记，避免与确定失败混淆。
3. **证据形态**：冻结 `evidence` 为快照 id 列表（`store.add_snapshot`），草案为 dict + 内联 `FocusSnapshot`。Phase 2 须把 `FocusSnapshot`/干扰证据经 `store` 落库并以 id 引用，方能塞进冻结 `evidence: list[str]`。
4. **审批双门叠加**：冻结 `SafetyGate.check_action(approval_token)` 颁令/校验高影响令牌；草案 `operation_requires_approval(impact)` 只做“是否需审批”标记、不发令牌。Phase 2 须把路由 `requires_approval=True`（含 `HIGH` 影响）接到 `SafetyGate` 的令牌校验，二者叠加而非替代。
5. **重试**：冻结 `ActionExecutor` 单次执行、无重试循环，原则 6 当前由构造保证。Phase 2 若引入重试，必须先调 `decide_retry(state, idempotent, ...)`；非幂等 `UNCONFIRMED`/`FAILED` 不得自动重试。
6. **actor 契约信息丢失**：冻结 `ActionExecutor.actor(...) -> bool`，草案 `UIAExecChannel.invoke/... -> ActionResult`（四态）。bool 返回值丢四态/风险，桥接适配器须保留草案 `ActionResult` 供信封序列化，不能只取 bool。
7. **操作命名对齐**：冻结 TOOL_SPECS 为 `trae.send_task`/`trae.get_status`/`trae.read_result`；草案能力表用 `send_task`/`get_task_status`/`read_task_result`。Phase 2 须统一 operation 命名（能力表键 ↔ TOOL_SPECS ↔ Engine 方法），否则路由查表与工具分发对不上。
8. **`UIAExecChannel` 形式化通道仍待 B approve 接入**：Phase 1 实测逻辑在 `src/probe/uia_exec.py`；`packages/execution/uia_channel.py` 的 `UiaPatternChannel` 已从 NotImplementedError 空壳补为**草案实现**（注入 resolve/pattern_of/guard_for/read_state/verify，guard 包裹 pattern 调用 + 回读 + 四态分类，实测 `FOCUS_SWITCH` 风险；含 12 例 fake 单测 `tests/test_uia_channel.py`，并经 run `20261117T102127Z` 真实靶应用实测复现 3/3 `focus_switch`），但**未接入冻结执行器**。Phase 2 须裁决注入契约（resolver/verifier 签名与 frozen `ActionExecutor` 对齐）、把实测探针逻辑收敛为正式通道并经 B approve 后接入。

### 11.5 B 线裁决清单（解锁 Phase 2 的决策议程）

11.2 是“确认实测事实”的核对项；本节是 B 线需要**做出决定**的离散决策，每项给出选项与影响。编号用 R（裁决）以区别于 `docs/team-plan.md` 第 3 节已确认的历史决策 D1–D7。G0 通过 = 下列 R1–R5 落定 + 11.2 事实核对完成 + 双人 approve 留痕。

- **R1 契约冻结**：是否把草案 Router/FocusGuard/分类/重试/影响门/桥接从“草案”转冻结？选项：(a) 全部冻结进入 Phase 2；(b) 先冻结 Router+FocusGuard+分类，重试/影响门/桥接随 Phase 2 迭代。影响：决定 Phase 2 可依赖的契约面。
- **R2 MCP 信封是否扩展**（11.4 差异 1/2）：冻结两态信封无法表达 `UNCONFIRMED`/风险。选项：(a) 扩展 `api.md` 增加 `state`/`risk` 字段（契约改动，双人 approve，原则 6 语义对外保留）；(b) 不改 `api.md`，`UNCONFIRMED` 对外退化为失败、仅在引擎内部保留（`legacy_bridge` 已演示该退化）。影响：原则 6 的对外可见性。
- **R3 外部输入下的效果归因**（开放问题 5）：非输入通道窗口内有外部输入时 `verified=True` 是否降级 `UNCONFIRMED`？`FOREGROUND_INPUT` 自注入与外部输入如何分离？选项：(a) 契约层内置降级 + 分离自注入标记；(b) 维持实验层“污染弃用”，契约层暂不降级。影响：四态归因严谨度。
- **R4 操作命名约定**（11.4 差异 7）：能力表键 ↔ TOOL_SPECS ↔ Engine 方法统一用哪套？选项：(a) 以冻结 TOOL_SPECS 名为准（`get_status`/`read_result`），草案表改名对齐；(b) 保留语义名（`get_task_status`/`read_task_result`），Phase 2 加显式 crosswalk。影响：路由查表与工具分发一致性。
- **R5 live 测量授权**：`trae.send_task` 发送点击的 FocusGuard 实测仍 `unknown`，需用户**重新明确** live 写授权（既有“全部授权”不自动延伸）；agent 模式 live 禁止。选项：(a) 授权一次性 Chat 无害发送以实测 send_task 风险；(b) 维持 `unknown`，send_task 在 STRICT 下不可自动放行。影响：Trae 主通道风险能否定级。

**当前可执行证据**：224 单测通过 + 受控靶应用实测 run `20261117T100205Z`（3/3 `focus_switch`）+ 草案契约链实测组合 run `20261117T101352Z`（路由→分类→重试→桥接 3/3 贯通）+ 形式化 UIA 通道实测 run `20261117T102127Z`（3/3 `focus_switch` 复现）+ 自绘靶应用负例 run `20261117T102927Z`（内容无 UIA 语义）；草案桥接/重试/影响门/完整性守护/UIA 通道均有单测；Trae 适配器（能力 C）安全前置与回复提取纯逻辑亦有单测（`tests/test_trae_adapter_guards.py` 16 例：agent 模式未批准拒绝、非法模式拒绝、`extract_last_reply` 边界、审批文本提示——均在 CDP/store 之前触发，无 live 写、未改适配器或冻结契约）。R1–R4 为 B 线契约决策，R5 为用户授权决策；未决前不接入冻结模块。

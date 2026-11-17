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

严格无干扰模式禁止未经批准的焦点切换、物理鼠标移动和键盘注入。策略只决定“通道是否可选”，高影响操作的审批由既有 `SafetyGate` 独立执行，两者叠加而非互相替代。

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
| `FAILED` | 操作失败 |
| `UNCONFIRMED` | 结果无法确认（非幂等操作禁止自动重试） |

**表述纪律**：`SUCCESS_NO_INTERFERENCE_OBSERVED` 只表示“未观察到”，不能表述为“绝对无干扰”。文档与 UI 必须保留该限定。

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
| 明确识别不支持后台操作 | E5（含微信 4.x / Trae UIA 负例） | capability scan 输出 |
| Trae 实际能力有测试证据 | E6（只读复跑 + 授权 live 无害消息） | `src/probe/PROBE_REPORT.md` 增补；Chat 模式读回 `OK`、工作区零变更 |
| 所有实验可重复运行 | `src/probe/run_experiments.py` | 固定环境记录 + 原始 JSON |

## 10. 开放问题

1. ~~ctypes Win32 标准控件经 MSAA→UIA 桥的 pattern 可用性需 E1 实测~~ 已实测：Invoke/Value/Toggle/Text 均可用（E1/E1b/E1c），无需切换备选靶应用。
2. ~~FocusGuard 漏检率与采样频率的关系需量化~~ 已部分量化：事件钩子补捉轮询漏掉的瞬时切换（E1c）；`dwell_limit.py` 快注入实测停留低至约 8.9 ms，25/25 轮询+钩子检出、0 污染；<2 ms 理论盲区仍待量化。
3. Trae 版本升级后的选择器漂移由既有 heal 流程覆盖，需 Phase 2 复验。
4. 新契约需 B 线 approve 后才能从“草案”转为冻结（见第 11 节评审包）。

## 11. 契约评审包（待 B 线 approve）

本节汇总 Phase 1 形成的新契约草案与实测依据，供 B 线评审。**评审通过前不得接入冻结的 `engine` / `mcp_gateway` / Dashboard，不得变更旧契约（`element.py`、Engine Protocol、`locators.yaml`、`schema.sql`、`api.md`）。** G0 尚未正式通过。

### 11.1 待评审草案清单

| 草案 | 位置 | 状态 |
|---|---|---|
| `Channel` / `InterferenceRisk` / 策略过滤 | `packages/routing/capability.py`、第 3、6 节 | 草案 |
| `FocusSnapshot` / `FocusRun` / `FocusGuard` Protocol | `packages/focusguard/monitor.py`、`outcome.py`、第 4 节 | 草案 |
| 四态分类 `classify()` | `packages/focusguard/classify.py`、第 4.2 节 | 草案（含单测） |
| UIA 执行通道与风险声明 | `src/probe/uia_exec.py`、第 3.5 节 | 草案 |
| Trae 四接口契约 | 第 5.2 节 | 草案（Phase 2 正式接入） |
| 实测能力表 + 加载器 | `packages/routing/capabilities.draft.yaml`、`capability_table.py` | 草案（含单测） |

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

### 11.3 实测依据索引

- 基线 run `20261117T082451Z`、增补 run `20261117T090104Z`：`docs/experiments/background-control.md` 第 7、11 节。
- 短停留检测限 run `20261117T091848Z`：`src/probe/dwell_limit.py`，实测停留低至约 8.9 ms、25/25 检出（第 12 节）；精确计时复跑 run `20261117T093513Z` 最短可解析真实停留 15 ms（第 12.1 节）。
- 四态分类单测：`tests/test_phase1_classification.py`（14 例）——含 `detect_unexpected_focus_switch` 聚合（轮询漏记、仅钩子捕获仍判干扰）与 `hook_dwell_ms` 精确计时（含 32 位回绕、缺失对返回 None）。
- 路由契约单测：`tests/test_phase1_routing.py`（18 例）——锁定“实测 UIA=FOCUS_SWITCH 在 STRICT 下未批准被拒、批准后可用”、风险升序+通道优先级排序、fallback 排除被拒通道、UNKNOWN 永不可用、策略×风险×审批矩阵。对应 11.2 检查项 1、3 已有可执行证据。
- 实测能力表单测：`tests/test_capability_table.py`（7 例）——草案表加载、原生 UIA 实测 focus_switch、BALANCED 选 UIA / STRICT 未批准被拒、微信负例返回原因、Trae send_task CDP unknown 不自动放行、Trae 只读接口实测 none 可在 STRICT 放行。
- Trae 只读 CDP 焦点实测 run `20261117T092712Z`：`src/probe/trae_cdp_focus.py`，只读路径 5/5 无干扰（第 13 节）。
- FocusGuard 大样本可靠性 run `20261117T093120Z`：`src/probe/focusguard_reliability.py`，误报 0/30、检出 15/15（第 14 节）。
- 代码提交：`4665ab8`（P0 实验改进）。

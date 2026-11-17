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

Phase 1 不做动态学习或在线探测；能力表由 `src/probe/run_experiments.py` 的 E5 扫描输出并人工复核。

### 3.5 Phase 1 实测修正（2026-11-17）

`docs/experiments/background-control.md` 的 E1b 对受控 Win32 靶应用做了 3 种 pattern × 3 个后台窗口的隔离试验：

- 9/9 效果回读成功，9/9 光标位移为 0；
- 9/9 前台在动作窗口内切换到目标，9/9 未检测到外部输入；
- 因此该应用的 UIA 风险应声明为 `FOCUS_SWITCH`，不能默认 `LOGICAL_ONLY`。

设计修正：能力表按“应用 × 操作 × 控件 × 目标前后台状态”实测风险；`STRICT_NO_INTERFERENCE` 下未批准的 UIA 焦点切换仍应被拒。UIA 的“光标零位移”与“无焦点干扰”必须分开报告，不得用前者替代后者。

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

FocusGuard 采用动作前后快照 + 2 ms 前台/光标采样，不保证捕获两次采样之间的瞬时切换。Phase 1 E2 在约 120 ms 的注入切换上得到 3/3 检出、0/3 误报；更短切换的漏检率尚未量化。`GetLastInputInfo` 只能标记窗口内“存在输入事件”，不能区分输入来源；Physical Input 通道自身注入的输入需单独标记为动作注入。

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
| Trae 实际能力有测试证据 | E6（复跑探针） | `src/probe/PROBE_REPORT.md` 增补 |
| 所有实验可重复运行 | `src/probe/run_experiments.py` | 固定环境记录 + 原始 JSON |

## 10. 开放问题

1. ctypes Win32 标准控件经 MSAA→UIA 桥的 pattern 可用性需 E1 实测；失败则切换 PowerShell WinForms 靶应用（D1 备选）。
2. FocusGuard 漏检率与采样频率的关系需量化。
3. Trae 版本升级后的选择器漂移由既有 heal 流程覆盖，需 Phase 2 复验。
4. 新契约需 B 线 approve 后才能从“草案”转为冻结。

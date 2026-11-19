# GUIBridge v0.1 产品需求文档（PRD）

版本：v0.1-draft｜日期：2026-11-17｜状态：待评审
依据：`src/probe/PROBE_REPORT.md`（2026-11-17 实测）与原始研究方案《GUIBridge × AgentBridge》。

## 1. 定位

GUIBridge 是位于 AI Agent 与桌面应用之间的**语义控制中间件**：让没有开放 API 的桌面应用成为 Agent 可以发现、调用、验证的工具。

- 不是 OCR 自动点击器，不是 Computer Use 模型。
- 核心交付：**可验证的业务级 GUI 工具**（提交→状态→读回→独立验证）+ **自修复语义定位** + **全动作审计**。
- 参赛演示：Claude Code（规划 Agent）经 GUIBridge MCP 控制 Trae IDE 完成一个开发任务，独立验证器检查 Git 变更与测试；随后改变窗口几何再次执行，证明语义定位稳定。

## 2. 范围（重新基线）

| 能力 | 优先级 | 说明 |
|------|--------|------|
| 托管启动与窗口管理（含多显示器/DPI） | P0 | 注入可访问性/调试参数；窗口枚举与几何跟踪 |
| CDP 感知通道（Electron 应用） | P0 | 实测主通道 |
| UIA 感知通道（原生应用） | P0 | 通用引擎组成部分 |
| OCR 兜底通道 | P0 | RapidOCR；仅补盲 |
| 语义元素融合 + 稳定 semantic_id + 定位器注册表 | P0 | 多特征定位器，执行时重定位 |
| Trae 适配器：send_task / get_status / read_result | P0 | IDE 模式；状态机见 §7 |
| MCP Server（8 工具） | P0 | §6 |
| 事件存储与审计（SQLite + 截图证据） | P0 | 全动作可追溯 |
| 安全审批与窗口白名单 | P0 | §9 |
| 自修复定位器 | P1 | 失效检测→重扫→候选→验证→更新；歧义即停 |
| Claude → Trae 端到端交接 + 独立验证器 | P1 | 演示主链路 |
| Dashboard（Vue3） | P1 | 任务/事件/证据可视化 |
| OmniParser 视觉补充 | P2 | 非完成条件 |
| 多 IDE 并行控制 | P2 | 非完成条件 |

非目标：任意 Windows 软件全面兼容；后台/锁屏会话可用性承诺；取代已有 API/CLI 可靠接口（API-first、GUI-fallback）。

## 3. 技术路线（实测修正）

感知分层按**通道能力矩阵**选择，而非固定 UIA 优先：

1. **CDP DOM**：Electron/Chromium 应用（Trae、VS Code 系）。前提：GUIBridge 托管启动目标进程并注入 `--remote-debugging-port=<随机端口>`（仅 127.0.0.1）。提供 role/aria/class/data-testid/状态类全语义。
2. **UIA**：原生 Win32/WPF/WinForms；Electron 仅框架级（实测聊天 WebView 不可见），不作 Electron 主通道。
3. **OCR**：像素文本补盲（自绘区域、无 CDP/UIA 语义时）。
4. **视觉模型**：P2，仅图标级补盲。

冲突处理：多通道结果不一致时不执行，重新观察或请求人工确认。

**通道可靠性探针**：适配器加载时对每个候选通道做能力探针（如 CLI chat 投递验证），失败通道降级为候选而非主通道。Trae 3.6.13 实测 `trae chat` 静默失败 → 主通道为 CDP。

**读回通道**：主 = CDP 会话 DOM；备 = 回复归档扩展（需项目绑定与版本重验）。

## 4. 架构与目录

```text
Agui/
├── apps/
│   ├── dashboard/            # Vue3 + TS + Vite
│   └── desktop-agent/        # FastAPI 本地控制平面（托管启动、审批、事件流）
├── packages/
│   ├── perception/           # cdp.py / uia.py / ocr.py / vision.py / fusion.py
│   ├── semantic/             # element.py / resolver.py / locator_cache.py
│   ├── execution/            # actions.py / verifier.py / safety.py
│   ├── adapters/             # base.py / trae/{adapter.py, locators.yaml, states.py}
│   ├── events/               # store.py（SQLite 事件与证据）
│   └── mcp/                  # server.py
├── examples/demo-app/        # 演示用 Vue 示例项目（密码显示/隐藏任务）
├── src/probe/                    # 第一阶段探针与证据（只读归档）
├── tests/
└── docs/                     # PRD / dev-prompts / architecture / benchmark / security
```

数据流：MCP Client → MCP Server（参数校验/审批/审计）→ Adapter（业务状态机）→ Resolver（semantic_id→实时定位）→ Perception（通道）→ Execution（动作+前后快照）→ Verifier（后置条件）→ Event Store。

## 5. 核心数据模型

```python
@dataclass
class GUIElement:
    id: str                  # 运行时元素 ID
    semantic_id: str | None  # 注册表逻辑 ID
    window_id: str
    role: str
    name: str
    bounds: tuple[int, int, int, int]
    actions: list[str]       # click / invoke / type / select
    source: list[str]        # cdp / uia / ocr / vision
    confidence: float        # 启发式分数，未经校准不得解释为概率
    evidence: dict           # 通道原始证据（selector / automation_id / ocr_box）

@dataclass
class Locator:
    semantic_id: str
    app_version: str
    chain: list[dict]        # 有序定位策略：cdp_selector / uia_criteria / ocr_text / visual
    verification: str        # 后置条件名
    healed_at: str | None

@dataclass
class ActionResult:
    success: bool
    verified: bool           # 后置条件成立 ≠ 任务已验证
    error_code: str | None
    before_snapshot_id: str
    after_snapshot_id: str
    evidence: list[str]

@dataclass
class TaskRecord:
    task_id: str
    app: str
    state: str               # submitted / running / awaiting_approval / claimed_done / verified / failed / unknown
    transitions: list[dict]  # 时间戳 + 状态 + 证据 ID
```

三态区分（硬要求）：**已提交**（消息进入会话）≠ **Agent 声称完成**（界面显示完成）≠ **已验证**（Git/测试证据符合验收）。

## 6. MCP 工具定义（v0.1 固定 8 个，不随元素动态增删）

| 工具 | 输入 | 输出 |
|------|------|------|
| `gui.list_windows` | `{}` | 白名单内窗口：window_id、进程、标题、几何 |
| `gui.inspect_window` | `{window_id, max_depth?}` | GUIElement 列表（融合后） |
| `gui.find_element` | `{window_id, semantic_id? , role?, name?}` | GUIElement[]（含 confidence 与 evidence） |
| `gui.perform_action` | `{window_id, semantic_id, action, args?, approval_token?}` | ActionResult |
| `gui.get_snapshot` | `{window_id}` | snapshot_id、元素摘要、截图路径 |
| `trae.send_task` | `{project_path, task, mode?: chat\|agent, allow_files?, acceptance?}` | TaskRecord（state=submitted/failed） |
| `trae.get_status` | `{task_id}` | TaskRecord.state + 运行信号证据 |
| `trae.read_result` | `{task_id, max_chars?}` | 助手回复文本 + 证据 ID + claimed_done 标记 |

约束：`gui.perform_action` 对高影响控件（审批模式、删除、终端、Git 提交类）必须携带有效 approval_token；所有工具调用写事件存储；`confidence` 输出附带 `calibrated=false` 标记。

## 7. Trae 适配器状态机（Trae 3.6.13 实测基线）

前置：托管启动（或接管已启动且带调试端口的实例）→ 确认 IDE 模式（`.icube-mode-tab-item-ide`，SOLO 无 Chat 模式）→ 选择会话模式（`.popup-menu` 叶子精确匹配）→ **审批模式强制手动**（除非调用显式授权 auto）。

`send_task`：
1. 前置检查：窗口进程/标题匹配、IDE 模式、composer 存在且可聚焦。
2. 新建或复用会话（`data-testid=ai-chat-create-new-session`）。
3. focus composer → 插入文本 → 断言 send 按钮脱离 disabled。
4. 点击 send → 后置验证：用户消息节点出现在会话 DOM（submitted）。
5. 失败分类：locator_missing / focus_failed / not_submitted / ambiguous。

`get_status`：轮询会话 DOM 信号：
- running：innerText 含「思考中/生成中/运行中」或停止控件存在；
- awaiting_approval：手动审批弹窗/按钮特征（开发阶段 S2 实测补全）；
- claimed_done：无运行信号且出现新助手回复节点；
- unknown：信号冲突或超时 → 不猜测，上报。

`read_result`：读会话容器 innerText/结构化消息节点，截取末条助手回复；附 before/after snapshot 与证据 ID；**只标记 claimed_done，verified 由独立验证器授予**。

独立验证器（P1）：在测试仓库/worktree 中执行 `git status/diff` + 预定义测试命令；结果写 TaskRecord.transitions 并反馈规划 Agent。

## 8. 自修复定位器（P1）

触发：执行前重定位失败或身份校验不符（窗口/进程/角色/邻接文本）。
流程：重扫窗口 → 按注册表 chain 逐策略候选 → 身份验证（角色+父容器+邻接文本+视觉签名可选）→ 唯一候选才更新注册表并记录修复事件；**≥2 个相似候选即停止并请求人工确认**。
版本管理：locators.yaml 按 app_version 分节；探针发现漂移时生成候选补丁供人工审核，不静默覆盖。

## 9. 安全与权限

- 窗口白名单：仅操作用户显式选择的窗口；每次动作前核对进程与窗口身份。
- 审批：高影响动作（审批模式切换、终端、删除、安装、Git 提交/推送）需 approval_token；Agent 模式任务默认手动审批。
- 提示注入：IDE 聊天内容/README/网页文本一律视为不可信数据，不得改变权限与规则；读回文本进入 MCP 输出时标注 untrusted。
- CDP：仅 loopback、随机端口、会话结束关闭；不暴露给局域网；文档明示无认证风险与缓解。
- 隐私：默认仅截目标窗口；日志保留期可配置；src/probe/ 与证据目录不入公开交付。
- 环境限制：交互式桌面会话依赖；锁屏/UAC/远程桌面断开/多显示器 DPI 均可能失效 → 状态 unknown 而非盲执行（F8 实证）。
- 工作区隔离：演示与测试一律使用测试仓库或 git worktree。

## 10. 验收与基准

实验组：A 纯截图+视觉+坐标；B CDP/UIA+OCR 语义定位；C GUIBridge 适配器+状态验证。
场景：发送消息、切换模式、读取回复、窗口移动、窗口缩放、主题切换、异常弹窗；每场景 ≥10 次重复，记录失败类型。
目标（受支持场景，未实测前不作承诺）：成功率 ≥90%；窗口移动后 ≥90%；高影响控件误点击 0；动作可追溯率 100%。
演示验收：同一演示内改变窗口几何后再次 send_task 成功；独立验证器给出 verified；全程事件可回放。

## 11. 里程碑（自 2026-11-17 重新基线，14 天）

| 阶段 | 日期 | 交付 | 出口条件 |
|------|------|------|----------|
| S0 探针 | 11/16–17 | 已完成 | PROBE_REPORT GO |
| S1 感知与语义引擎 | 11/18–20 | CDP/UIA/OCR 通道 + 融合 + 注册表 | 可重复识别与点击 Trae composer/send |
| S2 适配器与 MCP | 11/21–23 | 状态机 + 8 工具 + 事件存储 | 外部 MCP Client 完成 send→status→read |
| S3 交接与验证 | 11/24–25 | Claude 规划 + 独立验证器 | 真实开发任务端到端 verified |
| S4 自修复与可视化 | 11/26–27 | 自修复 + Dashboard + 审批 UI | 窗口变化演示连续成功 |
| S5 基准与提交 | 11/28–30 | A/B/C 评测 + 演示站点 + 录屏 + 文档 | 站点公开可访问且不暴露本机权限 |

## 12. 风险与回退

| 风险 | 回退 |
|------|------|
| Trae 升级选择器漂移 | 版本分节注册表 + 自修复 + 探针重跑 |
| CDP 端口被安全软件拦截 | UIA 框架级 + OCR 混合定位，缩小演示范围 |
| 状态信号不足（长任务） | unknown 上报 + 归档扩展备通道 + 人工确认 |
| Qoder Sites 不支持本地执行器 | 站点仅展示 Dashboard 快照/录屏/评测；执行器本地运行 |
| 两周时间不足 | 砍 P1 自修复自动化，保留手动重定位演示；P2 全砍 |
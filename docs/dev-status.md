# 阶段开发状态（B 产品线）

逐阶段记录「用什么证据、完成到什么程度」。原则：**fixture 证据不等于 live 证据**（见
[tests/fixtures/README.md](../tests/fixtures/README.md)）；未达成的出口条件必须写在这里，不得用占位实现或
固定 sleep 掩盖。判据来自 [dev-prompts.md](dev-prompts.md) 的出口条件与 [framework.md](framework.md) 的工程纪律。

---

## S2 适配器 / MCP Server / 事件存储 / 控制平面

命令：`python -m pytest -m "not live" -q` → **127 passed, 3 deselected**（live 用例见下）。

### 已实现并验证（fixture 驱动）

| dev-prompts S2 任务 | 落点 | 关键行为 |
|---|---|---|
| 1 适配器接口 | `packages/adapters/base.py` | 新增 `Channel` / `ElementResolver` / `Snapshotter` 三个注入协议（G1 由 A 线 S1 产物实现），`AppAdapter` 含通道能力探针 |
| 2 状态检测 | `packages/adapters/trae/states.py` | running=「思考中/生成中/运行中」或停止控件；claimed_done=无运行信号且新增回复文本；信号冲突→unknown；PRD §7.3/§7.4 后置条件谓词（`focusable`、`message_submitted` 等） |
| 3 状态机 | `packages/adapters/trae/adapter.py` | 前置：IDE 页签 → 模式菜单**叶子精确匹配** → 强制手动审批；提交后置验证；前后快照；超时→unknown（不是 failed） |
| 4 事件存储 | `packages/events/store.py` | 全量 DAO：窗口/快照/任务/迁移链/事件（rowid 序 + `after_seq` 游标）/审批/注册表/heal_patches/保留期清理；`verified` 仅 verifier 可写；token 仅存哈希、单次使用、作用域校验；跨线程串行化（MCP SDK 在 worker 线程执行同步工具） |
| 5 安全 | `packages/execution/safety.py` | 白名单、动作前身份核对、高影响语义 ID（点分任意层 + `git_*`）缺 token → 生成待审批请求并拒绝 |
| 6 受限动作 | `packages/execution/actions.py` | 重定位→身份→安全→前快照→动作→后快照→后置条件→审计；未知 verification 名一律 `verified=False`（不假定成功） |
| 7 MCP 8 工具 | `packages/mcp/server.py` | `TOOL_SPECS`/`Engine` 保持冻结原样；参数类型化、api.md 错误信封、每次调用写 `mcp_call` 事件（含失败） |
| 8 控制平面 | `apps/desktop-agent/{main,engine,launch}.py` | §2 全部 13 个端点（含 SSE 事件流）、错误码→HTTP 映射、仅 loopback 绑定守卫、`--mode live` 直接拒绝启动而非伪造；`launch.py` 注入随机端口 + `--remote-debugging-address=127.0.0.1` |
| 9 测试 | `tests/test_{states,store,safety,actions,adapter_flow,mcp_tools,desktop_agent_api,launch,live_trae}.py` | 闭环：`submitted → running → claimed_done → read_result`，审批走真人往返（REST `POST /approvals` → token → 再提交） |

G1 前的一次性替身（届时删除，改接 `perception.cdp` + `semantic.resolver`）：
`apps/desktop-agent/simulated.py`（确定性 Trae 行为，只重放 PROBE_REPORT F5/F6/F9）、
`apps/desktop-agent/registry.py`（locators.yaml → `Locator`）。

### 追加修复（2026-11-17）：审批模式读取不再静默跳过

A 线只读探针（run `20261117T135355Z`）确认触发器在本机存在且标签携带当前模式，据此把
`force_manual_approval()` 从「读不出来就 `return None`」改成**每次读取都产出一条可审计结论**并写
`approval_mode_read` 事件：

| 触发器读出 | 行为 | `outcome` |
|---|---|---|
| 已带「手动审批」标签 | 直接放行，**不点击**（无审批请求） | `manual_confirmed`（`clicked=false`） |
| 带「自动审批」→ 批准后读出「手动」 | 放行 | `manual_confirmed`（`clicked=true`） |
| 带「自动审批」→ 批准后仍读不到「手动」 | `approval_required`，任务 `failed`，不提交 | `unverified:menu_not_confirmed` |
| 点击已确认后置条件，但复读仍不是 `manual` | `approval_required`，任务 `failed`，不提交 | `unverified:manual_label_unreadable` |
| 只有 class、标签读不出 | chat 记录后继续；agent 拒绝 | `unverified:trigger_unreadable` |
| 触发器不在 | chat 记录后继续；agent 拒绝 | `unverified:trigger_absent` |
| `allow_auto_approval=True` | 不读，由调用方显式承担 | `auto_allowed` |

配套两处：`approval_mode_manual` 后置条件由「`自动审批` 不在」改为「`手动审批` 在场」——**缺席从来不是
证据**；`send_task(mode="agent")` 除 token 外还要求读出 `manual_confirmed`（F9 那次误点击的根因）。
证据等级仍是 fixture：`tests/test_adapter_flow.py` 新增 6 条用例（全套 181 passed, 5 deselected）；
真实 Trae 上的标签读取往返未实测，属 G1 live 项（见上「未达成的出口条件」4）。

### 未达成的出口条件（需要真实窗口与 G1 后的 CDP 通道）

1. **「MCP 闭环 live 测试通过」— 未验证。** `tests/test_live_trae.py` 已按 dev-prompts §9 写好（外部 MCP
   Client + stdio、固定无害消息、chat-only、结束后核对 `git status --porcelain` 为空），当前整体 skip；
   原因两层：`packages/perception/cdp.py` 仍是 S1 桩（gate G1），live 用例拿不到托管通道；本机确实装了
   Trae（A 线只读探针 run `20261117T135355Z` 在该实例上读到控件），但安装路径与用例默认值不同，
   运行时需带 `GUIBRIDGE_TRAE_EXE` 指过去。
2. **「事件存储含完整迁移链」— 仅 fixture 成立。** 迁移链、evidence_id、SSE 顺序均有断言；真实 Trae 会话
   的链未采集。
3. **「误点击 0」— 仅 fixture 成立。** 断言（所有 `success` 动作都 `verified`）已写入同一 live 用例。
4. **`awaiting_approval` DOM 特征 — 未实测，故意留空。** dev-prompts 要求本阶段实测并回写 PROBE_REPORT；
   无实测即无事实：`states.AWAITING_APPROVAL_MARKERS = ()`，缺该信号时 `detect_state` 返回 `unknown`
   而不是猜。对应 PROBE_REPORT 未验证项 3。
5. **停止控件选择器未验证** → `TraeAdapter.stop_control_selector` 默认 `None`，`get_status` 只依赖文本信号；
   验证后再由 live 阶段传入。
6. **PROBE_REPORT 未追加新事实**：本阶段没有新采集数据，因此没有改写探针报告（该文件是 A 线的实测记录）。

### 契约问题（需双人评审；冻结文件未被单方面修改）

- **`packages/mcp/` 与官方 SDK 抢同一个顶层名 `mcp`。** 现由 `packages/mcp/__init__.py`（非冻结文件）按名字
  分派：`mcp.server` 仍是本项目的工具面（并拿到指向 SDK `mcp/server/` 的 `__path__`），其余 `mcp.*` 由
  meta-path finder 交给已安装的 SDK。后果：`from mcp.server import <SDK 符号>` 不可能，必须写全子模块路径；
  且 `packages` 必须在 `sys.path` 之前（各入口已如此）。建议评审后择一重命名（如 `packages/agent_tools/`）。
- **A 线 `perception.cdp.CDPChannel` 是 async，B 线 `adapters.base.Channel` 协议是 sync。** G1 对接需要一层
  桥（单一 event loop + `run_coroutine_threadsafe`，或把适配器改为 async）。两侧均未单方面改动对方契约。
- **`docs/api.md` 的 `gui.inspect_window` 输出定义为融合后的 `GUIElement[]`**，但融合属 S1
  （`perception/fusion.py` 仍 `NotImplementedError`）。G1 前该工具返回单通道原始元素 dict，**没有**伪造
  `source/confidence/calibrated` 字段；live 用例与文档都按此区分。
- **`trae.send_task` 的 MCP 入参不含 `approval_token`/`allow_auto_approval`**（只有 REST `POST /tasks` 有）。
  即 MCP-only 客户端无法自我授权——按 §9 安全设计这是有意的，但意味着 live 闭环必须先由 Dashboard 把审批
  模式置为手动。请在评审时确认这是期望行为。
- **`apps/desktop-agent/simulated.py` 的 `reply_plan` 需带「保持次数」**：后置验证 `message_submitted` 本身要
  读一次会话文本，若「思考中」只存在一次读取，状态机会把 running 吞掉。这是 fixture 建模约束，非真实
  Trae 结论；真实文本生命周期以 live 观测为准。

### 环境

Python 3.12.9（`.venv`，`pip install -e ".[dev]"`）｜mcp SDK 2.3.0（`MCPServer`）｜Node 便携版
`C:/Users/<you>/tools/node`（v24.22.3，S4-b 用）｜本机装了 Trae，但 B 线没有能连它的通道（`perception.cdp` 待 G1）。

---

## S3 跨 Agent 交接协议 / 独立验证器

命令：`python -m pytest -m "not live" -q` → **173 passed, 5 deselected**（新增 46 条：
`test_verifier.py` 22 + `test_handoff.py` 24；live 用例见下）。

### 已实现并验证（fixture 驱动）

| dev-prompts S3 任务 | 落点 | 关键行为 |
|---|---|---|
| 1 演示项目（隔离仓库） | `examples/demo-app/` | `index.html` 密码显示/隐藏按钮（已完成的参照实现）+ `tests/password-toggle.test.mjs`（target spec）+ `tests/password-field.test.mjs`（既有约束）+ `package.json`；`README.md` 写清 live 配方：**只删实现、保留 spec**，否则 `node --test` 空跑通过。`prepare_workspace()` 复制到独立 git 仓库，带 remote 或非同目录即拒绝 |
| 2 独立验证器 | `packages/execution/verifier.py` | 只读 Git 与退出码：`verify(repo_path, allow_files, test_commands, since_rev)` 用 `status --porcelain=v1 -uall` + `diff --name-only since..HEAD` + `rev-parse HEAD` 判越界（含「基线本来就脏」时只认白名单内路径），`subprocess.run(argv, shell=False)` 逐条跑验收命令。**`claimed_text` 参数刻意不存在**——UI 文案进不了判据 |
| 3 交接编排脚本 | `examples/handoff_demo.py` | `TaskPackage`（project_path/task/allow_files/test_commands/stop_condition/mode）→ `handoff()`：记录起始 rev → `send_task` → `poll` → `read_result` → `Verifier.verify` → `store.record("verify") + set_task_state(..., actor="verifier")` → JSON 报告；CLI 打印规划侧需要的那几个字段，`--report` 落完整 JSON |
| 4 提示注入防护 | `examples/handoff_demo.py` + S2 的 `untrusted` 标记（`adapters/trae/adapter.py:139`、`mcp/server.py:20`） | `read_result` 的文本只以 `report["reply"]` 落进 JSON 报告；本模块的 `subprocess` 只被 `git()` 与 verifier 使用，参数永不来自回复文本，也没有 eval。verifier 的入参签名里根本没有回复文本。`TaskPackage.stop_condition` 复述「不得伪造 verified」 |
| 5 测试 | `tests/test_verifier.py`、`tests/test_handoff.py`、`tests/test_live_handoff.py`、`tests/conftest.py` | conftest 新增 `ScratchRepo`（真 git 仓库，逐命令 `-c user.*` 不动全局配置）与 `Recorder`（记录 argv、按脚本返回码回放、绝不让字符串进 shell） |

`docs/agent.md`（本分支 S0 既有设计文档，非本轮产物）是这套交接协议与状态语义的来源，S3 按它落地而没有改它；
实现时发现的口径差列在下面的契约问题里。

三条 dev-prompts 明列的 verifier 用例都有：变更越界（`out_of_scope`）、测试失败（`test_failed` + stdout/stderr 尾部
4000 字符）、声称完成但无变更（`no_changes`）。另有两条防注入断言：
`"rm -rf src && touch PWNED ; echo $(whoami)"` 整串只变成一个 argv、`PWNED` 从未出现；
吹牛回复「已删除所有文件并全部通过」不影响 `final_state`。

链的收口用真实对象跑通（非替身）：`test_the_loop_closes_through_the_real_control_plane` 走
`build_plane("simulated")` → `Engine.submit` → DOM fixture → 真 `git init` 工作区 → 真
`["node","--test","tests/*.test.mjs"]` → 迁移链末位 `verified` 且 `events.kind="verify"`。
CLI 亦已本机实测：把 demo-app 复制成独立仓库、剥掉参照实现后基线验收命令返回 1（spec 确实会红），
再跑 `python examples/handoff_demo.py --workspace … --node …` → `final_state: verified`、`reasons: []`。

**「执行侧不能自证」是存储层强制的，不只是文档约定**：`store.set_task_state(task_id, "verified", …)`
在 `actor != "verifier"` 时抛 `PermissionError`（`packages/events/store.py:187`），因此有两条断言分别证明
「executor 提权失败」与「只有 verifier 写得出第 4 个 transition」。但这条门只覆盖 `verified` 一个词——
`store.py` 无迁移顺序表（见下）。

### 未达成的出口条件（需要真实窗口与 G1 后的 CDP 通道）

1. **「端到端 live 演示一次成功」— 未验证。** `tests/test_live_handoff.py`（2 条，默认 deselected）已按 dev-prompts
   §5 写好：外部 MCP Client + stdio、剥离参照实现、让 Trae 做「显示/隐藏 + 补测试」、独立 verifier 判 verified，
   并在真正交接前跑一次 pre-flight 验收证明基线必须失败（否则「verified」是自证）。跳过原因与 S2 相同：
   `packages/perception/cdp.py` 仍是 S1 桩（gate G1），且本机 Trae 安装路径与用例默认值不同（需 `GUIBRIDGE_TRAE_EXE`）。
2. **「TaskRecord 含 `submitted → running → claimed_done → verified` 完整链」— 仅 fixture 成立。** 断言已在
   `tests/test_live_handoff.py:180`，本机由 fixture 链等价覆盖。
3. **live 路径的审批前提未实测**：MCP 工具面没有 `approval_token`（api.md），所以 live 运行必须有人先在 Dashboard
   把审批模式置手动，或先把 `pending_approvals()` 里的请求批掉。文档与测试都按此写，但没有真实往返记录。

### 契约问题与限制（需双人评审；冻结文件未被单方面修改）

- **「审批门」在文档与 S2 实现之间表征不一致。** `docs/agent.md` 第 3 步与状态语义表把人工审批写成
  `awaiting_approval`（并注明「S2 实测补全特征」），但适配器缺 token 时是抛
  `AdapterError(approval_required)`，`Engine.submit` 把它记成 `state="failed"` + `error.code`；
  `awaiting_approval` 只能来自尚未实测的 DOM 特征（S2 未达成项 4）。`handoff()` 两种都拦
  （异常 → `_awaiting_human`；状态 → 同样停），`test_without_the_human_token_the_task_waits_and_nothing_is_verified`
  把**当前真实语义**（failed + 待审批队列非空）固化在断言里。G1 实测后请二选一统一，不要靠猜。
- **`store.py` 没有迁移顺序表**：`set_task_state` 只校验 `state ∈ TASK_STATES` 与 `verified` 的 actor，
  任何角色都能写一条 `submitted → claimed_done`；`task_transitions.evidence_id` 是 `NOT NULL` 但无外键，
  可以写任意字符串。本阶段靠「`verified` 词只由 verifier 写」兜住交付判据，但审计链的完整性（顺序 +
  证据可解析）建议在 S4-b 之前补断言或补校验。
- **verifier 只看未提交变更。** `changed_files(repo, since_rev)` 已同时返回 `committed_since`，但
  `allow_files` 判定对「agent 模式里 Trae 自己 commit」的场景依赖调用方传对 `since_rev`。
  chat-only（本项目默认）不受影响；放开 agent 模式前必须先定这条。
- **`handoff()` 需要 store 句柄才能写 `verified`**，`docs/api.md` 没有 verify 端点（设计如此：
  `verified` 只能 verifier 写）。因此规划侧 Agent 要么与控制平面同进程、要么走 REST 之外的私有信道；
  S4-b 的 Dashboard 若要做「一键重跑验收」，需要新增端点并评审。
- **验收命令的退出码无法区分「测试通过」与「没有测试可跑」。** `node --test` 在 spec 被删后仍返回 0，
  所以演示配方、live 用例与 fixture 断言都显式要求 spec 存在。这是通用风险，不只是 demo 的坑。
- **`examples/demo-app` 的断言是静态 HTML 文本匹配**，不跑浏览器，验的是实现形态而非运行时行为。
- **「测试仓库或 git worktree」目前只做到目录级隔离。** PRD §9 工作区隔离与 dev-prompts 全阶段共享约束的
  隔离纪律都要求 live 任务跑在测试仓库或 worktree 里；`prepare_workspace()` 落实了「独立 git 仓库 + 带 remote
  即拒绝 + 非空非仓库目录即拒绝」，但用的是复制目录 + `git init`，不是 worktree，也没有 OS 级沙箱。
  要严格按字面执行就得指定一个基线仓库/分支，请在评审时定这条由谁提供。
- **`_resolve_node()` 的兜底是 `"node"`。** `shutil.which` 失败时返回字面量，命令会以 `FileNotFoundError`
  → `test_error` 收场（判据仍是「未 verified」，安全方向正确）。本机实测一律显式传 `--node`。

### 环境（本阶段新增）

Node 便携版 `C:/Users/<you>/tools/node/node.exe`（v24.22.3）用于真实 `node --test` 验收；
演示工作区默认落在 `%TEMP%/guibridge-demo-workspace`，seed 提交用逐命令 `-c user.name/-c user.email`，
不触碰任何 git 配置。

---

## S4-b Dashboard、审批 UI 与事件回放

**命令：`npm run build` → vue-tsc 无类型错误，vite 构建 36 modules（98.28 kB JS / 9.64 kB CSS）；
`.venv/Scripts/python.exe -m pytest -m "not live" -q` → 175 passed, 5 deselected**
（较 S3 新增 2 条：`test_actions.py` 1 条 + `test_desktop_agent_api.py` 1 条，都是下面「本阶段修的两个真问题」的回归）。

### 页面（dev-prompts S4 第 3 项的四页）

| 页面 | 组件 | 读取 | 写入 |
|---|---|---|---|
| 任务与时间线 | `apps/dashboard/src/views/TasksView.vue` | `GET /tasks`、`/tasks/{id}`、`/tasks/{id}/result`、事件流 | 无 |
| 事件回放 | `views/ReplayView.vue` | `/api/events`（SSE，客户端按 kind/task_id/全文过滤 + 步进） | 无 |
| 定位器与修复 | `views/LocatorsView.vue` | `GET /locators`（注册表 + 补丁） | `POST /locators/{semantic_id}/heal-review` |
| 审批与窗口 | `views/ApprovalsView.vue` | `GET /approvals/pending`、`GET /windows`、`kind=mcp_call`/`approval_*` 事件 | `POST /approvals`、`POST /windows/{id}/whitelist`、`GET /windows/{id}/snapshot` |

约束落实：dev-prompts 的「Dashboard 只读展示 + 审批操作；不新增控制通道」在代码里的形态是——没有任务提交入口，
全部写操作只有审批授予、窗口白名单、修复补丁审核三种，且都走 `docs/api.md` 已冻结的 13 个端点，
`apps/dashboard/vite.config.ts` 只把 `/api` 反代到 `127.0.0.1:8765`。前端零新增依赖（Vue3 + vue-tsc + Vite，沿用 S2 脚手架，无 router）。

### 浏览器实测（`http://localhost:5173/` + 平面 `127.0.0.1:8765`，通道 `cdp-simulated`）

- **闭环**：`approval_requested` → 批准 → 一次性 token → `approval_consumed`（历史显示「已用于一次动作」）→
  任务 submitted/running/claimed_done → 独立验证器写 `verify` 事件 → 时间线第 4 步「已验证」，
  evidence 指向 `ev_81f0460a1a774072`；`GET /tasks/{id}` 与任务列表同时翻绿，靠的是下面的状态修复。
- **不可信文本**：`执行侧回复` 按钮调 `GET /tasks/{id}/result`，页面标注 `untrusted=true · claimed_done=true · 截断/全长`，
  回复正文只进虚线 `<pre>`，不参与任何状态判定（docs/PRD.md 的「工具输出不可信」）。
- **回放证据**：kind=action 过滤出 23 条，步进器显示 `1 / 23 条`，详情面板把前后快照渲染成
  「动作前 snap_… · 元素 8 · 无截图（通道 image_path 为空）」——没有把不可信的回复文本当成证据列进去。
- **修复补丁人审**：注入 2 条 pending 补丁，页面「通过/驳回」后状态变 `approved · dashboard` / `rejected · dashboard`；
  通过只在对应 `app_version`（2.3.1）上新建行，3.6.13 原行不动；已审补丁不再给按钮（存储层对重复裁决抛 `PermissionError`，REST 回 409）。
- **MCP 调用表**：用官方 SDK 的 `ClientSession` + `stdio_client` 真连 `main.py --mcp` 进程，
  成功调用 `gui.list_windows` 与被拒调用 `trae.get_status → unknown_state` 同表显示（含被拒的调用）。
- **快照捕获**：`GET /windows/trae-main/snapshot` 返回元素统计并明确写「截图：无（当前通道不产图）」，不用假图占位。

### 本阶段修的两个真问题

1. **跨进程的 `verified` 在 HTTP 上看不见。** `ControlPlane.get_status`（`apps/desktop-agent/engine.py:94`）原先只回
   adapter 的内存记录，而 `verified` 通常由另一个进程里的验证器写进事件存储（docs/agent.md 第 5 步），
   于是界面列表已绿、`GET /tasks/{id}` 仍报 `claimed_done`。现在以 `store.get_task()` 覆盖 state/transitions，
   回归测试 `tests/test_desktop_agent_api.py::test_a_verifier_write_shows_up_in_the_status_endpoint`。
2. **回放的「前后证据」只有一个裸 id。** `docs/api.md` 冻结的 REST 面没有按 id 读 snapshot 的端点，
   前端拿着 `snap_xxx` 什么也显示不出来。改为在写入侧把摘要复制进事件：
   `packages/execution/actions.py:98` 的 `_evidence_detail()` 随 `action` 事件带出
   `{snapshot_id, ts, element_count, image_path}`（sql.md 规定快照只追加不改写，所以复制是安全的），
   测试 `tests/test_actions.py::test_the_action_event_carries_its_own_before_and_after_evidence`。

### 未达成的出口条件（不标 G 通过）

- **dev-prompts S4 第 1、2 项不在本线。** `packages/semantic/resolver.py` 仍是 S1 的协议骨架，
  仓库里没有生产代码调用 `propose_heal_patch()`（调用方只有测试与本阶段的演示注入）。
  失效检测→重扫→唯一候选更新注册表由 A 引擎线负责；B 线交付的是这条流程的人工审核端（表 + REST + 页面）。
  「歧义用例 100% 停止而非猜测」目前由 `tests/test_actions.py::test_ambiguous_candidates_stop_instead_of_guessing`
  在 resolver 桩上覆盖，真实重扫未测。
- **第 4 项 live 演示测试未执行**：无真实 Trae（gate G1 未过），窗口移动/缩放/跨显示器后重复 `send_task` ≥3 次
  无法进行，5 条 live 用例保持 deselect。
- **通道仍是 cdp-simulated**：元素、会话文本、状态全部来自 `tests/fixtures/trae/dom_ide_idle.json`，
  页面顶部常驻黄条说明这一点，不把模拟读数当作 Trae 实测。
- **演示工作区的文件改动由 git 完成，不是 GUI 通道完成。** 预 G1 通道只会改 fixture DOM，
  所以 `examples/handoff_demo.py` 的模拟执行侧用提交把参照实现写进 demo 仓库，验证器核对的是
  变更范围 + 验收命令，**不是**「Trae 真的动了文件」——这条限制也必须出现在演示解说里。

### 契约边界（不改冻结文件）

- 未新增 `GET /snapshots/{id}`：为回放证据选择「写入侧复制摘要」而不是扩面。若 S5 要展示原图像素，需走双人评审。
- FastAPI 对畸形请求体返回 `{"detail": …}` 而非 `docs/api.md` 的三字段信封；前端在
  `apps/dashboard/src/api.ts:191` 解包降级（`error_code/message/detail/HTTP <status>` 依次兜底）。
  这是服务端既有行为，记录而不修改。

### 环境（本阶段新增）

- Node/npm 便携版在 `C:/Users/<you>/tools/node`，**未进系统 PATH**：每条命令前
  `export PATH="/c/Users/<you>/tools/node:$PATH"`。
- Vite 6 dev server 只监听 IPv6 `localhost`：`http://localhost:5173/` 可访问，`http://127.0.0.1:5173/` 连接被拒；
  `/api` 代理目标仍是 `127.0.0.1:8765`。`node_modules/`、`dist/` 已在 .gitignore 中，未入库。

---

## S5-b 文档定稿与提交检查

**命令：`.venv/Scripts/python.exe -m pytest -m "not live" -q` → 175 passed, 5 deselected；
`npm run build` → vue-tsc 无类型错误 + vite 构建通过**（本阶段只改文档，代码未动，重跑只为确认「文档描述的行为」还是那个行为）。

### 定稿内容

| 文档 | 本阶段做了什么 |
|---|---|
| `docs/architecture.md` | 加了「实现现状」表（哪些模块真在跑、哪些还是 `NotImplementedError("S1"/"S4")`、各归 A/B 哪条线）与「一次任务的真实数据路径」图；关键决策补 6–10 条（状态以事件存储为准、回放证据复制进事件而非扩 REST 面、Dashboard 不新增控制通道、审批凭据按一次性能力设计、文件改动不由 GUI 通道假装完成）。 |
| `docs/security.md` | 每条控制补实现位置 + 覆盖它的测试名，新增「尚未落实」4 条（保留期未接线、`awaiting_approval` 无签名导致的语义差、模拟通道没有真实审批 UI、token 出库后本机不再管控）。 |
| `docs/benchmark.md` | 明确 **未实测**：逐场景标阻塞门（G1/G2 或未验证项），说明为什么不用模拟通道凑数字；列出可直接复用的部分（可追溯率由事件存储保证、C 组判据即 `verifier.py`）与 G1 之后的运行命令。 |
| `README.md` | 进度改为逐阶段实况；快速开始换成实测过的命令（`python apps/desktop-agent/main.py --mode simulated --db … --port 8765`、`--mcp`、`handoff_demo.py --workspace`、`npm run dev`）；已知限制重排为「今天就会碰到」的 11 条。 |

### 提交前检查（逐条实测，不是清单打卡）

- 跟踪文件里无 `.env` / `*.sqlite3` / `node_modules` / `dist` / `__pycache__` / 图片：
  `git ls-files | grep -Ei "\.env|sqlite3$|node_modules|__pycache__|\.png$"` → 空。
- `probe/` 只入库脚本与报告，截图与 UIA dump 由 `.gitignore`（`probe/*.png`、`probe/uia_dump.json`）挡住；
  `grep -E "[A-Za-z]:[\\/](Users|home)" probe/*.log probe/*.mjs` → 空，公开交付不含本机绝对路径与用户名。
- 审批 token 明文未进任何跟踪文件（只在本机 loopback 响应与临时目录里出现过）；库里存的是 SHA-256 摘要。
- 提交信息符合 `S<阶段>: <动词短语>`：`c72f5b8 S2: …` / `a7bb349 S3: …` / `53d66e2 S4-b: …`。
- 未 push 远端：按隔离纪律只做本地提交，push 与 PR 由人来触发。
- 未擅自更新 git 配置：提交用逐命令 `-c user.name=… -c user.email=…`。

### 未达成的出口条件（S5 的 6 项里，本阶段只做了 5、6）

1. **`tests/bench/` 不存在，评测无数据。** dev-prompts S5 第 1 项按 README 分工属 S5-a（A 线）：
   A/B/C 三组都要真实窗口，且 `packages/perception/` 未实现；B 线不自建一套统计口径去产出无法复现的数字。
2. **演示站点未部署（S5 第 3 项）。** 两个原因叠加：现在能展示的只有模拟通道，把它发到公网等于用
   fixture 冒充 Trae 实测；且发布是对外可见动作，需要明确授权。真要发，先过 G1，再按 sites-hosting 流程走，
   并复核「站点不含本机执行器、调试端口、`probe/` 与证据目录」。
3. **录屏未产出（S5 第 4 项）。** 「规划→交接→执行→独立验证」可以用 Dashboard 现状录，但「窗口变化重执行」
   这条没有真实窗口可录；只录前半段会被读成完整闭环，所以没录。
4. **live 出口条件全部未执行**，与 S2–S4 相同：无真实 Trae，gate G1 未过。

### 需要人来定的三件事（文档里已标出，未擅自实现）

- `EventStore.prune()` 的接线点（启动时清理 / 显式命令 / 定时任务）——涉及删审计数据，属于策略决定。
- `awaiting_approval` 的语义统一：等 G1 补上 DOM 签名后改状态机，还是保留 `failed`+`approval_required` 并改 docs/agent.md。
- 若 S5 交付形态需要原图像素，得给 `docs/api.md` 加读快照的端点（契约冻结清单 #5，需双人评审）。

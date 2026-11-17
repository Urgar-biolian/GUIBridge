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

### 未达成的出口条件（需要 live 环境，本机无 Trae 安装）

1. **「MCP 闭环 live 测试通过」— 未验证。** `tests/test_live_trae.py` 已按 dev-prompts §9 写好（外部 MCP
   Client + stdio、固定无害消息、chat-only、结束后核对 `git status --porcelain` 为空），当前整体 skip；
   原因两层：本机没有 `D:\Program\Trae\Trae.exe`，且 `packages/perception/cdp.py` 仍是 S1 桩（gate G1）。
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
`C:/Users/lenovo/tools/node`（v24.22.3，S4-b 用）｜无 Trae。

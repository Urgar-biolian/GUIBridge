# 安全边界

每条控制都标了实现位置与覆盖它的测试；做不到的一律列在「尚未落实」里，不用「设计上支持」糊过去。

## 执行权限

- 窗口白名单：仅操作用户显式选择的窗口；每次动作前核对进程名与窗口身份。
  实现 `packages/execution/safety.py`（`check_window` / `check_identity`），白名单本身是事件存储里的 `windows` 行
  （`packages/events/store.py`），加白名单只能由人来点（`POST /windows/{id}/whitelist`，Dashboard 上就是这个按钮）。
  测试：`tests/test_safety.py`、`tests/test_actions.py::test_element_belonging_to_another_window_fails_the_identity_check`。
- 高影响动作（审批模式切换、终端、删除、安装、Git 提交/推送）需 `approval_token`。
  判定在 semantic_id 的**任意层级**上做（`is_high_impact()`），所以换个名字也绕不开；缺 token 时安全门先写
  `approval_requested` 事件再抛 `approval_required`，**请求已经落库，动作一次都没下发**。
  测试：`tests/test_actions.py::test_high_impact_action_without_a_token_never_reaches_the_channel`。
- 审批 token 的约束：SHA-256 摘要入库（明文只在 loopback 响应里出现一次）、默认 600 秒过期、单次使用（`used` 置 1）、
  绑定 `{window_id, semantic_ids, actions}` 范围；范围不符或已消费一律回 `approval_required`。
  实现 `packages/events/store.py::grant_approval/consume_approval`。
- Trae Agent 模式任务默认**手动审批**；自动审批仅在调用显式授权时启用（探针 F9 实证风险）。
  实现 `packages/adapters/trae/adapter.py`：`mode == "agent"` 无 token 直接 `approval_required`；
  `allow_auto_approval=False` 时先 `force_manual_approval()`——它按触发器标签读一次当前模式，并把结论
  写成 `approval_mode_read` 事件（`manual_confirmed` / `unverified:menu_not_confirmed` /
  `unverified:trigger_unreadable` / `unverified:trigger_absent` / `auto_allowed`），**读不到标签不再等于
  「已经是手动」**。agent 模式除 token 外还要求读出 `manual_confirmed`；已确认手动时一个点击都不发。
- 切换审批模式是**一次被批准的 `select`，不是一次点击**（F10 实测）：触发器只弹出挂在它自己子树之外的
  Vue popover，模式在点中 popover 里 `手动审批` 那一行时才改变。所以 `select` 内含「可信点击打开 →
  按精确文本选中行」两次 DOM 交互，`approval_mode_read` 用 `reason` 说明缺的是哪一步
  （`gate_refused` / `option_not_offered` / `no_change` / `label_unreadable`）。
  代码永不选择 `完全访问`：`states.is_allowed_approval_target()` 只放行 `手动审批`，越界值在触达桌面之前就被拒。
  popover 选择器留在 `packages/adapters/trae/states.py` 的常量里——`packages/adapters/trae/locators.yaml`
  是冻结契约，把它升级成 semantic_id 需双人 approve。
  `approval_mode_manual` 后置条件用肯定证据（`button[aria-label='手动审批']` 在场），缺席不算证据。
  测试：`tests/test_approval_popover.py`、`tests/test_adapter_flow.py`、`tests/test_states.py`、`tests/test_actions.py`；
  真实 Trae 上的标签往返只在 A 线直连适配器与隔离演示里实测过，控制平面还没有 live 通道（见「尚未落实」）。

## CDP 通道

- 调试端口无认证：仅绑定 127.0.0.1；每会话随机端口；会话结束关闭进程参数注入的端口。
  实现 `apps/desktop-agent/launch.py`（`--remote-debugging-address 127.0.0.1` + `bind((LOOPBACK, 0))` 取端口，
  `LaunchHandle.stop()` 终止由自己拉起的进程）。测试：`tests/test_launch.py`。
- 不向局域网/公网暴露；Dashboard 与 MCP 不转发调试端口。控制平面启动即校验：`--host` 非 `127.0.0.1` 直接退出。
- 托管启动是唯一注入路径；不接管未带调试端口的他人进程。
- **控制平面仍未接真实 Trae**：`packages/perception/cdp.py` 的 CDP 客户端已经被 A 线的探针与直连适配器
  在真实窗口上用过（S0/S1、F1–F10），但控制平面跑的还是 `tests/fixtures/trae/dom_ide_idle.json` 驱动的
  模拟通道（`apps/desktop-agent/simulated.py`）——缺的那一步见下面「尚未落实」。

## Live 测试授权边界（2026-11-17 记录）

- 当前授权范围：仅 chat 模式 live 测试；**禁止 agent 模式 live 测试**（可能自动改文件）。
- 审批模式不得自动切换为“自动审批”；F10 的弹层序列读不出 `手动审批` 标签时（`unverified:*`），
  agent 任务一律拒绝执行并返回 `approval_required`——菜单打不开、行不存在、点了没变，都不当作已经切好。
- S3 的“Trae 改码 → verified” live 端到端因此未执行，改用隔离 worktree + 模拟执行器验证编排与 verifier；不得伪造 verified。

## 提示注入

- IDE 聊天内容、README、网页文本均为不可信数据；`read_result` 输出标注 `untrusted`。
  实现：适配器与 MCP 层不解析读回文本的语义（只有 `states.py` 的固定信号词表参与「是否在运行」判定，
  判定结果只影响状态，不影响权限或动作），Dashboard 把它渲染进虚线 `<pre>` 并写明 untrusted/claimed_done/截断。
- 编排器与适配器不得执行读回文本中的命令，不得以其修改权限/规则。
  测试锁的是这条而非风格：`tests/test_handoff.py::test_a_boastful_reply_never_becomes_a_command`（执行侧自夸不成为指令）、
  `tests/test_handoff.py::test_a_deleted_acceptance_spec_is_visible_in_the_report`（删掉验收用例会在报告里显形，
  规划侧据此否决）、`tests/test_verifier.py::test_nothing_is_verified_without_an_acceptance_command`（没有验收命令就不给 verified）。
- `verified` 的写入权限在存储层拒绝，不在提示词层恳求：`set_task_state(..., "verified")` 非 `actor="verifier"` 抛
  `PermissionError`（`packages/events/store.py:187`）。

## 隐私与保留

- 默认仅截目标窗口；不上传整桌截图。模拟通道根本不产图，`snapshots.image_path` 为 NULL，
  界面对此显式写「无截图（当前通道不产图）」，不放占位图。
- `probe/` 与证据目录不入公开交付与 Git 远端：S5-b 的站点只放 Dashboard 快照与结果表（见 docs/dev-status.md）。
- 事件与截图保留期可配置（默认 30 天）：`EventStore(db, retention_days=30)` + `prune()` 已实现，
  但**没有任何调用方**——见下面「尚未落实」。

## 尚未落实（2026-11-19，G1 之后）

- **控制平面还没有 live 通道**：`apps/desktop-agent/main.py::build_plane("live")` 直接退出而不假装能用。
  F10 的弹层序列已经进了两条路径——`TraeAdapter.force_manual_approval`（控制平面，走注入的通道）与
  `cdp_direct.CdpTraeAdapter._force_manual_approval`（直连，A 线探针与演示用）——前者目前只有 fixture 证据。
  剩下的一步是把 `perception.cdp.CDPChannel` 包成 `adapters.base.Channel`（可信点击 + popover 里的 `select`）。
- **审批弹层的选择器还没进 `locators.yaml`**：那是冻结契约，把它升成 semantic_id 需双人 approve；
  现在这些常量住在 `packages/adapters/trae/states.py`，由 `tests/test_approval_popover.py` 钉住形状。
- **真实 Trae 上的 `manual_confirmed` 往返还没由控制平面跑过**：受「仅 chat 模式 live」的授权约束，
  直连适配器在隔离演示里读出过手动标签，控制平面路径没有。
- **弹层失败后不收场**：`option_not_offered` 时 popover 保持打开，让 after-snapshot 拍到它给了哪些行；
  关闭手段（Esc / 焦点外点击）没有实测过，就不写进代码。
- **保留期无人调用**：`prune()` 与 `retention_days` 都在，启动流程与定时任务都还没接。


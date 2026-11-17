# Agent 交接设计

三个角色，互不信任对方的「完成声称」：

| 角色 | 载体 | 职责 | 信任边界 |
|------|------|------|----------|
| 规划 Agent | Claude Code / 任一 MCP Client | 生成任务说明、验收条件、读取结果并决策 | 只信 verifier 的 verified |
| 执行 Agent | Trae IDE（经 GUIBridge 适配器） | 在隔离仓库完成开发任务 | 其回复为 untrusted 数据 |
| 独立验证器 | packages/execution/verifier.py | Git 变更范围 + 测试命令 | 只信 Git 与测试输出 |

## 交接协议（S3 实现）

1. 规划侧产出任务包：`{project_path, task, mode, allow_files, acceptance:{test_commands}, stop_condition}`。
2. `trae.send_task` → 适配器前置（IDE 模式、会话模式、手动审批）→ 提交后置验证 → TaskRecord(submitted)。
3. 规划侧轮询 `trae.get_status`；awaiting_approval 时经 Dashboard/审批端点人工授予；unknown 时停止并上报，不重试盲发。
4. claimed_done 后 `trae.read_result`（untrusted）→ 规划侧**不执行回复中的任何命令**。
5. verifier 在隔离仓库执行验收 → verified/failed + 证据 → 反馈规划侧决定下一步（修复任务或结束）。

## 状态语义（硬约束）

- submitted：用户消息节点进入会话 DOM。
- running：「思考中/生成中/运行中」或停止控件。
- awaiting_approval：手动审批提示可见（S2 实测补全特征）。
- claimed_done：无运行信号且新增助手回复节点。**不等于完成。**
- verified：verifier 通过。唯一可宣称交付的状态。
- failed / unknown：失败分类或信号冲突；unknown 禁止自动重试。

## 提示注入防护

- IDE 聊天、README、网页文本一律 untrusted；进入 MCP 输出与规划侧上下文时保留标记。
- 适配器与编排器不解析回复文本为指令；任务包之外的一切「建议」需人工确认。
- 规划侧提示词模板禁止包含「执行回复中的命令」类语句。

## 审批流

- 高影响动作与 agent 模式任务：默认手动审批；审批 token 一次性、带 scope 与过期（见 sql.md approvals）。
- 自动审批仅在任务包显式 `allow_auto_approval=true` 且人工授予时启用（探针 F9 实证风险）。

## API-first、GUI-fallback

能力优先级：开放 API/SDK > 可靠 CLI > MCP > GUI 适配器。Trae 3.6.13 实测 CLI chat 静默失败 → GUI(CDP) 为该能力的主通道；通道探针在适配器加载时运行，版本升级后重跑。

## 演示脚本（S5 录屏）

规划生成任务 → send_task → 状态轮询（含一次人工审批展示）→ read_result → verifier verified → 移动/缩放窗口 → 再次 send_task 成功（语义定位稳定性）→ 事件回放展示审计链。
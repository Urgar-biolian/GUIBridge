# 变更记录

格式遵循「保持 a Changelog」精神：按版本倒序，区分 Added / Changed / Fixed / 已知未验证。
能力状态的单一事实源是 [docs/dev-status.md](docs/dev-status.md)，本文件只记版本级摘要。

## v0.1.0-alpha — 2026-11-21（development preview）

状态：实验性开发预览。模拟闭环可运行；部分隔离桌面能力已实测；统一 live 执行链集成中。
**不建议用于无人值守的生产环境。**

### Added

- S0 技术探针与路线裁决（CDP 优先）；PRD、接口契约、事件 schema。
- S1 感知层：CDP / UIA / OCR 三通道、空间融合与冲突标记、`semantic_id` resolver 与 locators 注册表。
- S2 适配器 / SQLite 事件存储 / loopback 控制平面（REST + SSE）/ 固定 8 工具 MCP 面 / 安全门（白名单、身份核对、一次性审批 token）。
- S3 跨 Agent 交接与独立验证器：`submitted→running→claimed_done→verified`；验证器只信 Git 变更范围与验收命令退出码；两条交接演示（控制面路径 / MCP 路径）。
- S4-a 自修复定位：漂移重扫 → 唯一候选 → 复验 → 待审核补丁；多候选 `conflict` 停止。
- S4-b Dashboard（Vue3 + TS）：任务时间线、SSE 事件回放、定位器 heal 审核、审批授予。
- Phase 1 受控实验：FocusGuard / Router / 重试策略 / 四态信封；隐藏桌面隔离与主机零干扰实测；Rust `gbmirror` 原生镜像/录制与只读观测面板。
- 真实 Trae chat 发送一次经授权实测（固定无害消息、仅 chat 模式、零光标干扰、回复读回成功）。
- fixture 模拟 A/B/C 基准入库（`tests/bench/`）；569 项非 live 测试。
- MIT 许可与依赖许可证审计（docs/licenses.md）。
- 公开展示页（交互演示 + 架构 + 实测摘要）。
- 产品门面重构：README 产品主页 + 能力状态表、四层 docs/quickstart.md、CONTRIBUTING / SECURITY / CHANGELOG、仓库内截图与架构图（标注模拟 / live 口径）。

### Changed

- MCP 入口明确化：`packages/mcp`（SDK 2.x）为官方推荐面；`packages/mcp_gateway`（SDK 1.x FastMCP）降为实验/兼容面，依赖 pin 调整为 `mcp>=2`。
- 内部协作内容（双人分工、执行约定、过程文档索引）自 README 移入 `docs/development/`。
- 第三方应用实验统一加「非官方、受限兼容、无平台授权」声明。

### Fixed

- F10 审批弹层：切换手动审批收进一次被批准的 `select`（可信点击开弹层 + 精确文本选行）；读不到标签即拒绝执行。
- 交接演示在干净克隆上可复跑：`prepare_workspace` 新副本自动播种「改动前」基线；模拟模式自带写入代层（恢复参考实现，声明为模拟证据），独立运行不再因 `no_changes` 判 failed。
- 版本库卫生：调试日志移出、`*.log` / `var/` / 数据库文件忽略规则；历史敏感信息扫描（无凭据/截图/数据库残留）。

### 已知未验证（不列为能力）

- 控制平面 live 通道（`--mode live` 拒绝启动）；Trae 真实改码 live 端到端（禁止 agent 模式 live）。
- live A/B/C 基准对照；跨显示器 DPI；录屏路径；真实大型应用的隐藏桌面镜像。
- 事件保留期清理调用方未接线；`awaiting_approval` 无实测 DOM 签名（当前表现为 `failed` + `approval_required`）。
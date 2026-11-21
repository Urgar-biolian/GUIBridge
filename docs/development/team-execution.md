# 开发协作约定（内部过程文档）

本目录收纳开发过程与协作约定类文档：它们对贡献者有用，但不属于产品门面。
产品入口见根 [README](../../README.md)，上手见 [quickstart](../quickstart.md)，能力状态单一事实源见 [dev-status](../dev-status.md)。

## 双人分工（本仓库执行约定）

| | 咱们（用户 + Qoder 本会话） | 对方 |
|----|---------------------------|------|
| 开发线 | **A 引擎线** | **B 产品线** |
| 分支 | `feat/a-perception` | `feat/b-control-plane` |
| 范围 | S1 感知通道/融合/重定位/注册表；S4-a 自修复定位；S5-a 评测 A/B 组与通道探针 | S2 适配器/MCP/事件存储/控制平面；S3 verifier 与交接编排；S4-b Dashboard 与审批 UI；S5-b 站点/录屏/提交 |
| 开发提示词 | dev-prompts 的 S1（含 S4-a、S5-a 职责） | dev-prompts 的 S2（含 S3、S4-b、S5-b 职责） |

执行约定：

- **live 环境**：Trae 单实例运行在咱们机器；所有 live 测试与评测在咱们机器排队执行（对方可在 G1/G2 请求代跑）。对方 fixture-first 开发，不依赖真实 Trae。
- **集成门**：G1→G5，见 [docs/team-plan.md](../team-plan.md)；过门时双方合入 main 跑集成测试。
- **契约文件**（element.py / Engine Protocol / locators.yaml / schema.sql / api.md）改动需双人 PR approve；非契约单人 approve。
- 每日 15 分钟同步；阻塞先查 fixtures 与契约，不私改接口。
- 分工调整需双方确认，并同步更新本节与 team-plan。

## 内部过程文档索引

| 文档 | 内容 |
|------|------|
| [docs/team-plan.md](../team-plan.md) | 进度、双人并行分工、集成门、日历 |
| [docs/dev-prompts.md](../dev-prompts.md) | S1–S5 分阶段 Qoder 开发提示词 |
| [docs/framework.md](../framework.md) | 技术选型、工程纪律、契约冻结清单、构建命令 |
| [docs/delivery-checklist.md](../delivery-checklist.md) | 交付收尾清单：门状态、live 运行清单与授权门、录屏分镜、提交检查 |
| [docs/handoff-a-to-b.md](../handoff-a-to-b.md) | A 线交给 B 线的合并清单：新增模块、契约差异、冲突处理预案 |
| [docs/review-r1-r6.md](../review-r1-r6.md) | B 线对 A 线 R1–R6 契约裁决、Phase 1 事实核对意见与合并预案 |
| [docs/architecture/guibridge-design.md](../architecture/guibridge-design.md) | 任务书对齐架构：Router / FocusGuard / Trae 契约（草案） |
| [docs/research/competitor-analysis.md](../research/competitor-analysis.md) | agent-desktop 公开能力对比（仅公开资料） |
| [docs/research/originality-log.md](../research/originality-log.md) | 原创性与第三方依赖许可证记录 |
| [docs/research/license-audit.md](../research/license-audit.md) | A 线全量审计（Python/Rust/npm，含 MPL 文件级义务说明） |
| [docs/experiments/background-control.md](../experiments/background-control.md) | E1–E15 后台控制实验（非官方、受限兼容实验，见文首声明） |
| [docs/proposals/wechat-foreground-input.md](../proposals/wechat-foreground-input.md) | 微信前台输入方案提案（待评审，未生效） |
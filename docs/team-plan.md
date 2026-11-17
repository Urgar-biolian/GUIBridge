# 开发进度与双人并行计划

基线日期：2026-11-17｜交付窗口：11/18–30（14 天重新基线，PRD §11）

## 1. 当前进度

| 项 | 状态 | 证据 |
|----|------|------|
| S0 技术探针 | ✅ 完成 | probe/PROBE_REPORT.md：GO，CDP 优先路线；闭环实测 |
| 方案评审 | ✅ 完成 | 外部引用 5/5 属实；3 处判断修正 |
| PRD / 开发提示词 | ✅ 完成 | docs/PRD.md、docs/dev-prompts.md |
| 项目骨架 | ✅ 完成 | 单测 4 通过；模块可导入；Dashboard 浏览器实测+构建通过 |
| 契约与文档 | ✅ 完成 | element.py / Engine Protocol / locators.yaml / schema.sql / api.md |
| S1 感知与语义引擎 | ✅ 完成（11/17，早于 G1） | feat/a-perception `0e46c61`；单测 32 通过；live 只读定位 3 连过；融合冲突用例返回 conflict |
| S2 适配器与 MCP | ⬜ 未开始 | dev-prompts S2 |
| S3 交接与验证 | ⬜ 未开始 | dev-prompts S3 |
| S4 自修复与 Dashboard | ⬜ 未开始 | dev-prompts S4 |
| S5 基准与提交 | ⬜ 未开始 | dev-prompts S5 |

## 2. 双人分工（两条并行线）

执行映射（2026-11-17 确认）：咱们（用户 + Qoder 本会话）= A，分支 `feat/a-perception`；对方 = B，分支 `feat/b-control-plane`。live 环境与代跑约定见 README「双人分工」。

**A = 引擎线（感知/语义/定位/评测）**
- S1：perception/cdp.py、uia.py、ocr.py、fusion.py；semantic/resolver.py、locator_cache.py；tests/fixtures 录制；live 定位测试。
- S4-a：自修复定位（resolver.heal、heal_patches 流程、歧义停止单测）。
- S5-a：tests/bench A/B 组脚本与原始记录；通道能力探针维护。
- 产出物：通道 SDK + 定位服务 + 评测数据。

**B = 产品线（适配器/控制平面/交接/展示）**
- S2：adapters/trae（states、adapter）、execution（actions、safety）、events/store.py、mcp/server.py、desktop-agent（托管启动/审批/SSE）。
- S3：verifier、examples/demo-app 隔离仓库、handoff_demo 编排。
- S4-b：Dashboard 全页面 + 审批 UI + 事件回放。
- S5-b：演示站点（Qoder Sites）、录屏、benchmark.md 汇总、architecture/security 定稿、提交检查。
- 产出物：MCP 闭环 + 端到端演示 + 参赛交付。

## 3. 并行解耦机制

- **契约冻结**（framework.md 清单）：数据模型、Engine Protocol、注册表格式、schema、api.md 已冻结于骨架；B 在 A 完成 S1 前用 `tests/fixtures/` 录制快照 mock 通道开发状态机与 MCP。
- **集成门**：
  - G1（11/20 EOD）：A 交付通道 SDK + live 定位 3 连过；B 的 fixture 单测全绿。双方对接 resolver↔actions。
  - G2（11/23 EOD）：MCP send→status→read live 闭环（B 主调，A 陪跑定位问题）。
  - G3（11/25 EOD）：端到端 verified（S3）。
  - G4（11/27 EOD）：窗口变化演示 + 自修复歧义用例 + Dashboard 回放。
  - G5（11/30）：评测数据 + 站点 + 录屏 + 提交。
- **每日同步** 15 分钟：阻塞、契约变更请求、live 环境占用（Trae 单实例，live 测试排队）。
- **分支**：feat/a-* / feat/b-* → Gitee PR → 双人 approve（契约文件）或单人 approve（非契约）→ main。

## 4. 里程碑日历

| 日期 | A | B | 门 |
|------|---|---|----|
| 11/18–19 | CDP/UIA 通道 + 融合 | store/safety/actions + 状态机 fixture 单测 | |
| 11/20 | OCR + resolver + 注册表 + live 定位 | MCP server + desktop-agent 骨架接 fixture | G1 |
| 11/21–22 | 定位稳定性（窗口几何）+ fixtures 扩充 | 适配器 live 前置/提交/状态 | |
| 11/23 | 陪跑集成 | MCP 闭环 live | G2 |
| 11/24–25 | bench 脚本雏形 | verifier + demo-app + 编排 | G3 |
| 11/26–27 | 自修复 + 歧义单测 | Dashboard + 审批 UI + 回放 | G4 |
| 11/28–29 | A/B/C 评测执行 | 站点 + 录屏 + 文档定稿 | |
| 11/30 | 评测复核 | 提交检查 | G5 |

## 5. 风险与预案

| 风险 | 预案 |
|------|------|
| B 被 A 的通道进度阻塞 | fixture-first 已解耦；G1 延期则 B 继续 fixture 线，A 优先 CDP 最小可用 |
| Trae 单实例 live 冲突 | live 测试排队表；评测夜间批跑 |
| 选择器漂移 | 注册表版本分节 + 探针重跑；A 负责 |
| 人力不足 | 砍 S4 自修复自动化（保留手动重定位演示）；P2 全砍；Dashboard 减页 |
| Sites 后端限制 | 静态站点+录屏回退（S5-b 停止条件） |
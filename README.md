# GUIBridge

让没有开放 API 的桌面应用，成为 AI Agent 可以发现、调用和验证的工具。

语义控制中间件：CDP / UIA / OCR 多通道感知 → 稳定 semantic_id 定位 → 业务级 MCP 工具 → 状态验证与全动作审计。
参赛方向：Qoder 高校创造力大赛｜目标平台：Windows｜首个适配器：Trae IDE。

## 当前进度（2026-11-17）

- ✅ S0 技术探针：GO，路线修正为 CDP 优先；提交→状态→读回闭环实测成功（[src/probe/PROBE_REPORT.md](src/probe/PROBE_REPORT.md)）
- ✅ PRD、分阶段开发提示词、项目骨架、接口契约、数据库 schema
- ✅ S1 感知层（A 线，commits `0e46c61`）：CDP/UIA/OCR 三通道、空间融合与冲突标记、semantic_id resolver 与 locators 注册表；单测 32 绿；live 只读定位连续 3 次通过
- ✅ S4-a 自修复定位（A 线，`c92f3b4`）：漂移后按旧链 hints 重扫 → 唯一候选 → CDP 复验 → 写 pending 补丁（不覆盖注册表）；≥2 候选返回 `conflict` 停止；单测 46 绿 + live 3 轮通过
- ✅ S2 适配器 / 事件存储 / MCP（A 线补齐）：SQLite 事件与任务状态机、安全门（白名单/身份/高影响审批）、受限动作执行、Trae 适配器（IDE/Chat 前置、可信鼠标模式切换、手动审批探测）、Engine 审计面、8 工具 MCP、桌面代理 REST/SSE；单测 83 绿；live MCP 闭环 `submitted→running→claimed_done` 并读回 OK，工作区无变更（F10–F12）
- ✅ S3 交接与独立验证（A 线）：`packages/execution/verifier.py` 仅信 git 变更范围与测试退出码；`examples/handoff_demo.py` 在隔离 worktree 中跑通 `submitted→running→claimed_done→verified`（模拟执行器）；回复文本恒标 untrusted、不执行。**受安全约束（仅 chat 模式 live、禁止 agent 模式 live），Trae 真实改码的 live 端到端未执行**，用模拟链验证编排与验证器
- ✅ S4-b Dashboard / 审批 UI（按整体完成度补齐）：Vue3+TS+Vite；任务与迁移时间线、SSE 事件回放（含 before/after snapshot id）、定位器注册表与 pending heal patches 审核、一次性审批授予；浏览器实测健康检查/列表/授权 token 展示均通过，`vue-tsc` + `vite build` 通过
- ✅ S5 评测（A 线）：`tests/bench/bench.py` A/B/C fixture 基准（7 场景 ×10，原始 JSON 入库）、`docs/benchmark.md` 实测与分析；架构/安全文档定稿
- ✅ Phase 0（独立研发任务书对齐）：架构/竞品/原创性/实验四份文档骨架、`probe → src/probe` 迁移、Router/FocusGuard/UIA 执行契约草案、原生靶应用骨架；新契约待 B 线 approve
- ✅ Phase 1 E1–E6 实验（A 线，`30378b2` + P0 增补 `4665ab8`）：受控 Win32 靶应用后台 UIA 9/9 光标零位移但 9/9 焦点切换；前台起步对照（E1c）9/9 仍出现瞬时焦点切换，事件钩子补捉轮询漏掉的 3 次；FocusGuard 停留曲线（实测 57–138 ms）轮询/钩子均 9/9 检出、误报 0/3；遮挡下 UIA 成功而坐标点击命中遮挡窗；微信可见窗口仅 4 个 UIA 框架节点（负例刷新）；Trae 授权 live 在 Chat 模式发送一条无害消息并读回 `OK`、工作区零变更；DPI 变更未执行
- ✅ Phase 1 契约验证补强（A 线）：实测能力表草案 + 加载器；FocusGuard 事件钩子精确计时（最短可解析停留 15 ms）与大样本可靠性（误报 0/30、检出 15/15）；只读 Trae CDP 实测无干扰（`send_task` 发送点击仍 `unknown` 待重新授权）；**任务书原则 6/7 落地为草案契约**——`retry_policy.decide_retry`（非幂等未确认禁自动重试）与路由层 `OperationImpact.HIGH` 审批门（高影响即便无干扰须批准），含路由/分类/重试组合单测与能力表完整性守护；`classify()` 修正使 `UNCONFIRMED` 可达、探针 UIA 风险按实测 `FOCUS_SWITCH` 报告（受控实测确认）；四态→冻结信封桥接草案（显式锁定 UNCONFIRMED 在两态信封下的退化，待 B 裁决）；UIA 形式化通道 `UiaPatternChannel` 补为注入式草案实现（未接入冻结执行器）；草案契约链实测探针 `verify_contract_chain.py`（路由→分类→重试→桥接 3/3 贯通）；自绘靶应用受控负例 `scan_selfdrawn.py`（run `20261117T102927Z`：内容无 UIA 语义、仅标题栏 chrome 按钮，原生对照有语义）入能力表草案，补齐原生/Electron/自绘三类对比；Trae 适配器（能力 C）安全前置与回复提取纯逻辑 16 例单测（agent 未批准拒绝、非法模式拒绝、`extract_last_reply` 边界，均在 CDP/store 前触发，无 live 写）；B 线裁决清单 R1–R5（设计文档 11.5）；全套 224 通过。新契约仍待 B 线 approve，未接入冻结 engine/MCP
- ⬜ S5 参赛交付：演示站点公开发布与录屏需用户确认后执行（公开发布属外部可见操作）；当前 Dashboard 可本地运行演示

## 双人分工（本仓库执行约定）

| | 咱们（用户 + Qoder 本会话） | 对方 |
|----|---------------------------|------|
| 开发线 | **A 引擎线** | **B 产品线** |
| 分支 | `feat/a-perception` | `feat/b-control-plane` |
| 范围 | S1 感知通道/融合/重定位/注册表；S4-a 自修复定位；S5-a 评测 A/B 组与通道探针 | S2 适配器/MCP/事件存储/控制平面；S3 verifier 与交接编排；S4-b Dashboard 与审批 UI；S5-b 站点/录屏/提交 |
| 开发提示词 | dev-prompts 的 S1（含 S4-a、S5-a 职责） | dev-prompts 的 S2（含 S3、S4-b、S5-b 职责） |

执行约定：

- **live 环境**：Trae 单实例运行在咱们机器；所有 live 测试与评测在咱们机器排队执行（对方可在 G1/G2 请求代跑）。对方 fixture-first 开发，不依赖真实 Trae。
- **集成门**：G1(11/20)→G5(11/30)，见 [docs/team-plan.md](docs/team-plan.md)；过门时双方合入 main 跑集成测试。
- **契约文件**（element.py / Engine Protocol / locators.yaml / schema.sql / api.md）改动需双人 PR approve；非契约单人 approve。
- 每日 15 分钟同步；阻塞先查 fixtures 与契约，不私改接口。
- 分工调整需双方确认，并同步更新本节与 team-plan。

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/PRD.md](docs/PRD.md) | 产品需求：范围/路线/数据模型/状态机/安全/验收/里程碑 |
| [docs/team-plan.md](docs/team-plan.md) | 进度、双人并行分工、集成门、日历 |
| [docs/dev-prompts.md](docs/dev-prompts.md) | S1–S5 分阶段 Qoder 开发提示词 |
| [docs/framework.md](docs/framework.md) | 技术选型、工程纪律、契约冻结清单、构建命令 |
| [docs/architecture.md](docs/architecture.md) | 模块边界与关键决策记录 |
| [docs/architecture/guibridge-design.md](docs/architecture/guibridge-design.md) | 任务书对齐架构：Router / FocusGuard / Trae 契约（草案） |
| [docs/research/competitor-analysis.md](docs/research/competitor-analysis.md) | agent-desktop 公开能力对比（仅公开资料） |
| [docs/research/originality-log.md](docs/research/originality-log.md) | 原创性与第三方依赖许可证记录 |
| [docs/experiments/background-control.md](docs/experiments/background-control.md) | Phase 1 E1–E6 后台控制实验：环境、结果、四态、验收与限制 |
| [docs/api.md](docs/api.md) | MCP 8 工具 + 本地 REST/SSE 规范与错误码 |
| [docs/sql.md](docs/sql.md) | SQLite 事件存储设计（DDL：packages/events/schema.sql） |
| [docs/agent.md](docs/agent.md) | 跨 Agent 交接协议、状态语义、提示注入防护 |
| [docs/security.md](docs/security.md) | 安全边界：白名单/审批/CDP/隐私/环境限制 |
| [docs/benchmark.md](docs/benchmark.md) | A/B/C 评测模板（S5 填实测） |

## 快速开始

```bash
# 1) 事件存储/适配器单测（离线）
python -m pytest -q

# 2) live 闭环（需 Trae 以 --remote-debugging-port=9222 启动，chat 模式）
GUIBRIDGE_LIVE=1 python -m pytest -q tests/test_live_mcp.py

# 3) 交接演示（隔离 worktree，模拟执行器，无 Trae 改动）
python -X utf8 examples/handoff_demo.py

# 4) Dashboard + desktop-agent
python -m uvicorn apps.desktop-agent.main:app --port 8765 --host 127.0.0.1
cd apps/dashboard && npm install && npm run dev

# 5) 基准
python -X utf8 tests/bench/bench.py --iterations 10
```

## 已知限制

- Live 测试仅限 chat 模式；agent 模式改码/长任务与审批菜单自动化在 3.6.13 上未获授权/不可用（F10）。
- Dashboard 通过既有 REST/SSE 契约展示快照 id，不内嵌截图文件（避免证据外泄）。
- 基准为 fixture 模拟，未调用视觉模型；主题切换/异常弹窗场景未评测。
- Phase 1 已完成 E1–E6 主实验与 P0 增补（E1c 前台对照、E2 停留曲线、微信 PID 扫描、Trae 授权 live）；DPI 变更未执行（会打断用户会话）；`dwell_limit.py` 快注入探针实测停留低至约 8.9 ms、25/25 检出（<2 ms 理论盲区未覆盖）；Trae live 仅限授权的一次 Chat 无害消息、agent 模式未验证，`docs/experiments/background-control.md` 第 10–12 节已标注保留项。
- 演示站点与录屏尚未发布（需用户确认公开发布）。


```bash
python -m pip install -e ".[dev]"
pytest -m "not live"          # 单测；live 测试需本机 Trae 且显式运行
(cd apps/desktop-agent && python -m uvicorn main:app --port 8765)
(cd apps/dashboard && npm install && npm run dev)
```

## 目录

```text
apps/dashboard/         Vue3 + TS 展示与审批
apps/desktop-agent/     FastAPI 本地控制平面
packages/perception/    CDP / UIA / OCR / vision / fusion
packages/semantic/      数据模型 / 重定位 / 注册表
packages/execution/     动作 / 验证器 / 安全门 / UIA 执行契约
packages/routing/       能力表 / 干扰策略 / 执行路由（Phase 0 草案）
packages/focusguard/    干扰监测与四态结果（Phase 0 草案）
packages/adapters/      适配器接口 / Trae（locators.yaml）
packages/events/        SQLite 事件存储（schema.sql）
packages/mcp_gateway/           固定 8 工具 MCP Server
examples/demo-app/      S3 交接演示目标项目
src/probe/              S0 探针脚本与证据
tests/                  单测 + live 标记集成测试
```

## 已知限制

- 仅支持交互式桌面会话；锁屏/UAC/远程桌面断开不保证可用。
- Trae 定位器基线为 3.6.13；其他版本需重跑探针。
- CDP 通道要求托管启动目标应用（仅 loopback 随机端口）。
- 骨架中 `NotImplementedError("Sx")` 为阶段占位，对应 dev-prompts 的实现任务。
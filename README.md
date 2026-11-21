# GUIBridge

让没有开放 API 的桌面应用，成为 AI Agent 可以发现、调用和验证的工具。

语义控制中间件：CDP / UIA / OCR 多通道感知 → 稳定 semantic_id 定位 → 业务级 MCP 工具 → 状态验证与全动作审计。
参赛方向：Qoder 高校创造力大赛｜目标平台：Windows｜首个适配器：Trae IDE。

许可证：[MIT](LICENSE)；第三方依赖许可审计见 [docs/licenses.md](docs/licenses.md)。

## 当前进度（2026-11-21，收尾后）

- ✅ S0 技术探针：GO，路线修正为 CDP 优先；提交→状态→读回闭环实测成功（[src/probe/PROBE_REPORT.md](src/probe/PROBE_REPORT.md)）
- ✅ PRD、分阶段开发提示词、项目骨架、接口契约、数据库 schema
- ✅ S1 感知层（A 线）：CDP/UIA/OCR 三通道、空间融合与冲突标记、semantic_id resolver 与 locators 注册表；只读定位 live 通过
- ✅ S2 适配器 / 事件存储 / 控制平面（两线合并）：`submitted→running→claimed_done→verified` 状态机、
  SQLite 全动作审计、安全门（白名单 / 身份核对 / 高影响动作 token）、固定 8 工具 MCP、
  loopback 控制平面（REST + SSE）与托管启动；A 线的直连 CDP 适配器与 `GUIBridgeEngine` 作为独立入口保留
- ✅ S3 交接与独立验证（两线合并）：`packages/execution/verifier.py` 只信 Git 变更范围与验收命令退出码；
  `examples/handoff_demo.py`（规划侧任务包）与 `examples/handoff_mcp_demo.py`（MCP 工具面）跑通
  `submitted→claimed_done→verified`，回复文本恒标 untrusted 且不执行。
  **受安全约束（仅 chat 模式 live、禁止 agent 模式 live），Trae 真实改码的 live 端到端未执行**
- ✅ S4-a 自修复定位（A 线）：漂移后按旧链 hints 重扫 → 唯一候选 → CDP 复验 → 写 pending 补丁（不覆盖注册表）；
  ≥2 候选返回 `conflict` 停止；审核入口在 Dashboard 与 `POST /locators/{id}/heal-review`
- ✅ S4-b Dashboard（B 线）：Vue3+TS+Vite 四页（任务时间线 / 事件回放 / 定位器与 heal 审核 / 审批与窗口），
  一次性审批授予、SSE 续传（`Last-Event-ID`）、无截图时显式声明
- ✅ Phase 1 实验与契约候选（A 线）：受控 Win32 靶应用的 FocusGuard / Router / 重试策略 / 四态信封桥接
  实测与单测，明细见 [docs/dev-status.md](docs/dev-status.md)
- ✅ G1 收尾第 1 项 F10（审批弹层）：切手动审批收进**一次被批准的 `select`**（可信点击开弹层 → 按精确文本选中行），
  直连与控制平面两条路径共用 `states.py` 的选择器与 JS，演示子类里的副本已删；证据仍全是 fixture，
  控制平面的 live 通道没接（`--mode live` 拒绝启动），详见 [docs/security.md](docs/security.md)
- ⬜ S5 评测：fixture 模拟 A/B/C 已实测并入库（`tests/bench/`）；**live 对照未实测**，
  阻塞项是 R5（真实 Trae 会话发送需用户授权）与 G2（跨显示器 DPI），见 [docs/benchmark.md](docs/benchmark.md)
- ✅ 收尾（2026-11-21）：项目许可定为 MIT、依赖许可证审计落 [docs/licenses.md](docs/licenses.md)、
  移出版本库的调试日志与 `*.log` 忽略规则、集成门日期与 handoff 对齐；冻结契约零改动
- ✅ 隐藏桌面与镜像（A 线，probe 侧）：隐藏桌面隔离运行靶应用、主机零干扰实测（E8/E15），
  Rust `gbmirror` 原生镜像/录制与 `gbdash` 只读观测面板，微信适配器与只读/零干扰发信实验；
  全部证据在 [background-control.md](docs/experiments/background-control.md) 第 15–29 节，
  逐条复跑命令见 [docs/delivery-checklist.md](docs/delivery-checklist.md)
- ⬜ S5 参赛交付：站点公开发布与录屏需用户确认后执行（公开发布属外部可见操作）
- 测试现状：`pytest -m "not live"` → 566 通过 / 3 跳过（MCP 网关需 `mcp<2`）/ 8 条 live 默认 deselect
- 每阶段「做到了什么、没做到什么」一律记在 [docs/dev-status.md](docs/dev-status.md)，不拿界面显示完成当交付

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
| [docs/licenses.md](docs/licenses.md) | 依赖许可证审计：逐包清单、MIT 兼容结论、未覆盖项 |
| [docs/research/license-audit.md](docs/research/license-audit.md) | A 线全量审计（Python/Rust/npm，含 MPL 文件级义务说明） |
| [docs/delivery-checklist.md](docs/delivery-checklist.md) | 交付收尾清单：门状态、live 运行清单与授权门、录屏分镜、提交检查 |
| [docs/proposals/wechat-foreground-input.md](docs/proposals/wechat-foreground-input.md) | 微信前台输入方案提案（待评审，未生效） |
| [docs/experiments/background-control.md](docs/experiments/background-control.md) | E1–E15 后台控制实验：UI 消息注入、隐藏桌面隔离、微信只读/零干扰、镜像与观测工具 |
| [docs/api.md](docs/api.md) | MCP 8 工具 + 本地 REST/SSE 规范与错误码 |
| [docs/sql.md](docs/sql.md) | SQLite 事件存储设计（DDL：packages/events/schema.sql） |
| [docs/agent.md](docs/agent.md) | 跨 Agent 交接协议、状态语义、提示注入防护 |
| [docs/security.md](docs/security.md) | 安全边界：白名单/审批/CDP/隐私/环境限制，含「尚未落实」 |
| [docs/benchmark.md](docs/benchmark.md) | A/B/C 评测：fixture 模拟实测数字 + live 未实测的逐行阻塞原因 |
| [docs/dev-status.md](docs/dev-status.md) | 阶段实现状态：出口条件逐条判定与未达成项 |
| [docs/review-r1-r6.md](docs/review-r1-r6.md) | B 线对 A 线 R1–R6 契约裁决、Phase 1 事实核对意见与合并预案（待双人 approve） |
| [docs/handoff-a-to-b.md](docs/handoff-a-to-b.md) | A 线交给 B 线的 G1 合并清单：新增模块、契约差异、冲突处理预案 |

## 快速开始

```bash
python -m pip install -e ".[dev]"
pytest -m "not live"                 # 566 passed / 3 skipped（MCP 网关要 `mcp<2`）/ 8 条 live 默认 deselect

# 控制平面（loopback only；--mode simulated 用 fixture 通道，不需要打开 Trae）
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --port 8765

# 给 Agent 用同一套能力，把 REST 换成 stdio MCP（8 个工具，每次调用写审计行）
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --mcp

# Dashboard（需要 Node 18+；只读展示 + 审批，不能提交任务）
cd apps/dashboard && npm install && npm run dev     # http://localhost:5173，/api 反代到 8765

# 交接演示：规划侧任务包 → 执行侧自称完成 → 独立验证器判定
python examples/handoff_demo.py --workspace C:/tmp/guibridge-demo-workspace --node node
python examples/handoff_mcp_demo.py                 # 同一条闭环走 MCP 工具面，需 `mcp<2` + node

# 基准（fixture 模拟的 A/B/C 三组，原始 JSON 入库）
python -X utf8 tests/bench/bench.py --iterations 10

# live 闭环（需真实 Trae 以 --remote-debugging-port=9222 启动、chat 模式，并逐条授权）
GUIBRIDGE_LIVE=1 GUIBRIDGE_LIVE_PROJECT=<隔离仓库路径> python -m pytest -q -m live
```

## 目录

```text
apps/dashboard/           Vue3 + TS 展示与审批：时间线、SSE 回放、heal 审核、token 授予
apps/desktop-agent/       控制平面：REST/SSE、模拟通道、托管启动、pre-G1 locator 载入 shim
packages/perception/      CDP / UIA / OCR / vision / fusion（A 线真实通道）
packages/semantic/        数据模型 / resolver / 自修复重定位 / locator 缓存与 capability table
packages/execution/       安全门 / 受限动作执行 / 独立验证器 / FocusGuard 桥接 / routed 执行器
packages/routing/         能力表路由 / 干扰策略 / 重试决策（Phase 0 草案）
packages/focusguard/      干扰监测、四态结果与扩展信封
packages/adapters/trae/   适配器：adapter.py（走执行器）+ cdp_direct.py（直连 CDP）+ locators.yaml
packages/adapters/wechat/ 微信适配器与 Win32/UIA 驱动（probe 侧接入，未进控制面默认路径）
packages/events/          SQLite 事件存储（schema.sql：windows / tasks / events / snapshots / approvals）
packages/mcp/             冻结的 8 工具 MCP Server（手写 stdio 帧，不依赖 mcp SDK）
packages/mcp_gateway/     A 线的 FastMCP 网关（`mcp<2`），与上面并存
packages/router_engine.py GUIBridgeEngine：A 线的通道路由入口（控制平面入口是 engine.ControlPlane）
examples/                 demo-app、两条交接演示、live agent 演示
src/probe/                探针与实验（S0/S1、隐藏桌面 E8–E15）、gbmirror（Rust）、gbdash（不入公开交付）
tests/                    单测 + fixtures + `@pytest.mark.live` 集成测试 + bench
```

## 已知限制

- 仅支持交互式桌面会话；锁屏 / UAC 安全桌面 / 远程桌面断开 / 多显示器 DPI 变化可能导致失效——
  状态报 `unknown` 并停止，不盲执行（探针 F8 实证漂移）。
- **Trae 真实改码的 live 端到端仍未执行。** 安全约束只允许 chat 模式 live、禁止 agent 模式 live；
  R5（真实会话发送以量化 `send_task` 的焦点风险）还需要用户本人授权。8 条 `@pytest.mark.live`
  用例默认 deselect，不在 G1 之前伪称通过。
- **审批模式不是点一下就能切的（F10）**：触发器只弹出一个 popover，模式要在其中选中 `手动审批` 那一行才改变，
  所以切换是一次被批准的 `select`（内含可信点击打开 + 按精确文本选行），代码永不选 `完全访问`；
  读不到「手动审批」标签时一律回 `approval_required` 并拒绝执行，不猜状态。控制平面这条路径还没有
  live 通道可跑（`--mode live` 直接退出），实测证据来自 A 线直连适配器与隔离演示。
  `awaiting_approval` 至今没有实测 DOM 签名（未验证项 3），当前表现为
  `failed` + `approval_required`，语义差记在 [docs/security.md](docs/security.md)。
- **模拟通道不改文件、不产截图**：离线闭环的 `verified` 证明的是变更范围 + 验收命令退出码 + 写入权限，
  不证明 GUI 真的动了手；`snapshots.image_path` 为 NULL，界面写「无截图」而不是放占位图。
- **基准数字是 fixture 口径**：策略排序（C 优于 A、B 会假成功）成立，绝对成功率衡量的是录制快照；
  live 一栏逐行标了阻塞原因。
- **不拿版本号当判据**：注册表基线是探针时的 3.6.13，本机实装回报 UA `Trae/1.107.1`、exe 元数据 3.4.20，
  三个号码互不一致；以 `semantic_id` 重定位能否命中当前 DOM 为准，整条链落空即 `locator_missing`，改版本需重跑探针。
- **两个 MCP 入口并存**：`packages/mcp`（B 线冻结的 8 个工具，手写 stdio 帧，不依赖 mcp SDK）与
  `packages/mcp_gateway`（A 线 FastMCP，需 `mcp<2`，SDK 2.x 把 `FastMCP` 改名成了 `MCPServer`）。
  工具名与错误码一致，接哪一个由调用方决定；本机装的是 2.x，相关用例跳过而不是伪称通过。
- **Dashboard 只能看和批，不能提交任务**：dev-prompts S4 的约束（不新增控制通道），不是漏做。
- **保留期只是配置项**：`EventStore(retention_days=30)` 与 `prune()` 都在，还没有调用方接线。
- CDP 通道要求托管启动目标应用（仅 loopback 随机端口），实现见 `apps/desktop-agent/launch.py`。
- **隐藏桌面镜像需要编译工具链**：原生镜像/录制用 `src/probe/gbmirror`（Rust，`cargo build --offline --release`），
  本机没有 Rust 时只有 Python 镜像 `src/probe/hidden_mirror.py`（需 Pillow，且当前绑定保活会话）；
  镜像/录制会显示真实画面，公开录屏须切 benign 靶。零干扰是采样观察值，<2 ms 盲区与 FocusGuard 相同。
- `apps/desktop-agent/registry.py` 是 pre-G1 的 locator 载入 shim，应由 `packages/semantic/locator_cache.py`
  取代，已列入合并待办（docs/handoff-a-to-b.md）。

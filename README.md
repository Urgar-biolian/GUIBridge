# GUIBridge

让没有开放 API 的桌面应用，成为 AI Agent 可以发现、调用和验证的工具。

语义控制中间件：CDP / UIA / OCR 多通道感知 → 稳定 semantic_id 定位 → 业务级 MCP 工具 → 状态验证与全动作审计。
参赛方向：Qoder 高校创造力大赛｜目标平台：Windows｜首个适配器：Trae IDE。

## 当前进度（2026-11-17）

- ✅ S0 技术探针：GO，路线修正为 CDP 优先；提交→状态→读回闭环实测成功（[probe/PROBE_REPORT.md](probe/PROBE_REPORT.md)）
- ✅ PRD、分阶段开发提示词、项目骨架、接口契约、数据库 schema
- ✅ S2（B 线）：Trae 适配器状态机、事件存储、固定 8 工具 MCP、loopback 控制平面（REST 13 端点 + SSE）
- ✅ S3（B 线）：独立验证器 + 跨 Agent 交接编排（`examples/handoff_demo.py`）
- ✅ S4-b（B 线）：Dashboard 四页（任务时间线 / 事件回放 / 定位器与人审 / 审批与窗口）
- ⬜ S1、S4-a（A 线）：CDP/UIA/OCR 感知通道与自修复重定位仍是骨架 → 集成门 G1 未过，**当前只有 fixture 驱动的模拟通道**
- ⬜ S5：评测未实测（见 [docs/benchmark.md](docs/benchmark.md)），站点与录屏待提交阶段
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
| [docs/api.md](docs/api.md) | MCP 8 工具 + 本地 REST/SSE 规范与错误码 |
| [docs/sql.md](docs/sql.md) | SQLite 事件存储设计（DDL：packages/events/schema.sql） |
| [docs/agent.md](docs/agent.md) | 跨 Agent 交接协议、状态语义、提示注入防护 |
| [docs/security.md](docs/security.md) | 安全边界：白名单/审批/CDP/隐私/环境限制，含「尚未落实」 |
| [docs/benchmark.md](docs/benchmark.md) | A/B/C 评测表（当前未实测，逐行标了阻塞原因） |
| [docs/dev-status.md](docs/dev-status.md) | 阶段实现状态：出口条件逐条判定与未达成项 |
| [docs/review-r1-r6.md](docs/review-r1-r6.md) | B 线对 A 线 R1–R6 契约裁决、Phase 1 事实核对意见与合并预案（待双人 approve） |

## 快速开始

```bash
python -m pip install -e ".[dev]"
pytest -m "not live"                 # 181 passed, 5 deselected（live 需真实窗口 + G1 后的 CDP 通道）

# 控制平面（loopback only；--mode simulated 用 fixture 通道，不需要打开 Trae）
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --port 8765

# Dashboard（需要 Node 18+；只读展示 + 审批，不能提交任务）
cd apps/dashboard && npm install && npm run dev     # http://localhost:5173，/api 反代到 8765
```

给 Agent 用同一套能力，把 stdio 服务换成 REST：

```bash
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --mcp
```

八个工具（`gui.*` / `trae.*`）走标准 MCP stdio，每次调用都写审计行；接法与错误码见 [docs/api.md](docs/api.md)。
演示「规划侧交接 → 执行侧自称完成 → 独立验证器判定」这条闭环：

```bash
# 目标目录若不存在，会从 examples/demo-app 复制出一个独立 git 仓库；带 remote 的目录一律拒绝
python examples/handoff_demo.py --workspace C:/tmp/guibridge-demo-workspace --node node
```

## 目录

```text
apps/dashboard/         Vue3 + TS 展示与审批
apps/desktop-agent/     FastAPI 本地控制平面
packages/perception/    CDP / UIA / OCR / vision / fusion
packages/semantic/      数据模型 / 重定位 / 注册表
packages/execution/     动作 / 验证器 / 安全门
packages/adapters/      适配器接口 / Trae（locators.yaml）
packages/events/        SQLite 事件存储（schema.sql）
packages/mcp/           固定 8 工具 MCP Server
examples/demo-app/      S3 交接演示目标项目
probe/                  S0 探针脚本与证据
tests/                  单测 + live 标记集成测试
```

## 已知限制

- 仅支持交互式桌面会话；锁屏/UAC/远程桌面断开不保证可用。
- Trae 定位器基线写在注册表里是 S0 探针时的 3.6.13，而本机实装回报的 UA 为 `Trae/1.107.1`、exe 元数据为
  3.4.20 —— 三个号码互不一致，所以**不拿版本号当判据**：以 `semantic_id` 重定位能否命中当前 DOM 为准，
  整条链落空即报 `locator_missing` 并停止，改版本需重跑探针。
- **没有真实 Trae 通道。** `packages/perception/` 与 `packages/semantic/` 仍是骨架，控制平面跑的是
  `tests/fixtures/trae/dom_ide_idle.json` 驱动的模拟通道；Dashboard 顶部常驻黄条说明这一点。
  模拟通道的元素、会话文本、状态都不是 Trae 实测。
- **模拟通道不改文件、不产截图。** 演示工作区的文件改动由 `examples/handoff_demo.py` 用 git 完成，
  所以「verified」证明的是变更范围 + 验收命令 + 事件写入权限，不证明「GUI 真的动了手」；
  快照 `image_path` 为 NULL，界面写「无截图」而不是放占位图。
- **需要人在 Trae 里点审批时看不出来。** `awaiting_approval` 没有实测 DOM 签名（PROBE_REPORT 未验证项 3），
  detector 宁可报 `unknown` 也不猜；当前表现为 `failed` + `approval_required`，语义差记在 docs/security.md。
- **Dashboard 只能看和批，不能提交任务。** 这是 dev-prompts S4 的约束（不新增控制通道），不是漏做。
- **事件与截图的保留期只是配置项。** `EventStore(retention_days=30)` 与 `prune()` 都在，但没有调用方。
- **评测数字为空。** A/B/C 三组全部依赖真实窗口，逐行阻塞原因见 [docs/benchmark.md](docs/benchmark.md)。
- 5 条 `@pytest.mark.live` 用例默认 deselect，未在 G1 之前伪称通过。
- CDP 通道要求托管启动目标应用（仅 loopback 随机端口），实现见 `apps/desktop-agent/launch.py`。
- 仅支持交互式桌面会话；锁屏 / UAC 安全桌面 / 远程桌面断开 / 多显示器 DPI 变化可能导致失效（报 unknown 并停止）。
- 骨架中 `NotImplementedError("Sx")` 为阶段占位，对应 dev-prompts 的实现任务。
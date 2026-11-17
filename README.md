# GUIBridge

让没有开放 API 的桌面应用，成为 AI Agent 可以发现、调用和验证的工具。

语义控制中间件：CDP / UIA / OCR 多通道感知 → 稳定 semantic_id 定位 → 业务级 MCP 工具 → 状态验证与全动作审计。
参赛方向：Qoder 高校创造力大赛｜目标平台：Windows｜首个适配器：Trae IDE。

## 当前进度（2026-11-17）

- ✅ S0 技术探针：GO，路线修正为 CDP 优先；提交→状态→读回闭环实测成功（[probe/PROBE_REPORT.md](probe/PROBE_REPORT.md)）
- ✅ PRD、分阶段开发提示词、项目骨架、接口契约、数据库 schema
- ⬜ S1–S5 开发：双人并行计划见 [docs/team-plan.md](docs/team-plan.md)

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
| [docs/security.md](docs/security.md) | 安全边界：白名单/审批/CDP/隐私/环境限制 |
| [docs/benchmark.md](docs/benchmark.md) | A/B/C 评测模板（S5 填实测） |

## 快速开始

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
- Trae 定位器基线为 3.6.13；其他版本需重跑探针。
- CDP 通道要求托管启动目标应用（仅 loopback 随机端口）。
- 骨架中 `NotImplementedError("Sx")` 为阶段占位，对应 dev-prompts 的实现任务。
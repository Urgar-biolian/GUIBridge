# 贡献指南

GUIBridge 是实验性项目（`v0.1.0-alpha`）。欢迎 issue 与 PR；请先读 [README](README.md) 的能力状态表与 [docs/dev-status.md](docs/dev-status.md)，确认你要改的部分处于什么证据口径。

## 环境

```bash
python -m venv .venv && .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest -m "not live"     # 569 passed / 3 skipped / 8 deselected
```

Dashboard 开发另需 Node ≥ 18（`apps/dashboard`，`npm install && npm run dev`）。
上手四层入口见 [docs/quickstart.md](docs/quickstart.md)。

## 工程纪律（硬性）

- **fixture-first**：新功能先有 fixture 与失败路径测试，再谈 live；不拿界面显示完成当交付。
- **证据口径分离**：fixture 证据 ≠ live 证据。文档与 PR 描述里逐条标注「已实测 / 模拟 / 未验证」。
- **三态纪律**：`submitted ≠ claimed_done ≠ verified`；`verified` 只能由独立验证器（Git 变更范围 + 验收命令退出码）授予。
- **读回文本恒 untrusted**：应用回复只复制、不执行、不解析为指令。
- **不用固定 sleep 判状态**：轮询间隔可以固定，状态推断必须来自可观测信号。
- **live 授权门**：live 测试默认 deselect；运行需 `GUIBRIDGE_LIVE=1`、隔离仓库、人工白名单与逐条授权；禁止 agent 模式 live。
- **不伪造数据**：跳过就写跳过原因，未实测就写未实测。

## 契约冻结

以下文件为冻结契约，改动需**双人 PR approve**（其余文件单人 approve）：

- `packages/semantic/element.py`
- `packages/mcp_gateway/server.py` 的 `TOOL_SPECS` 与 `Engine` Protocol（工具面契约同源 `packages/mcp/server.py`）
- `packages/adapters/trae/locators.yaml`
- `packages/events/schema.sql`
- `docs/api.md`

冻结能力表 `packages/routing/capabilities.draft.yaml`（status: frozen）同属契约数据，改动需双人 approve。

阻塞先查 fixtures 与契约，不私改接口。MCP 新接入推荐官方面 `packages/mcp`（SDK 2.x）；`packages/mcp_gateway` 为 1.x 实验/兼容面。

## 提交与 PR

- 分支自 `main` 切出；一个 PR 只做一件事，描述写清证据口径与复跑命令。
- 测试：`pytest -m "not live"` 全绿；涉及 live 路径的改动附授权与隔离说明。
- 提交信息沿用仓库现有风格（阶段/范围前缀 + 事实性描述）。
- **公开内容卫生**：不提交机器绝对路径、Windows 用户名、凭据、token、真实聊天内容、真实项目截图；
  实验证据原始数据放 `var/`（已 gitignore）；演示截图一律 benign 靶应用或模拟数据并标注口径。
- 第三方应用相关改动须保持「非官方、实验性兼容、无平台授权」声明，不得暗示平台背书。

## 安全

发现安全问题请按 [SECURITY.md](SECURITY.md) 报告，不要公开 exploit 细节。
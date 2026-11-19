# 工程框架与技术选型

## 技术栈

| 层 | 选型 | 理由 |
|----|------|------|
| 桌面感知 | Python 3.10+ / uiautomation / mss | UIA 与高速窗口截图 |
| Electron 感知 | websockets（CDP 客户端） | 实测主通道，全 DOM 语义 |
| OCR 补盲 | RapidOCR（optional extra `ocr`） | 中英文混合、本地推理 |
| 视觉补盲 | OmniParser（P2，不引入默认依赖） | 仅图标级 |
| 控制平面 | FastAPI + uvicorn | 本地 REST/SSE/审批 |
| Agent 接口 | 官方 MCP Python SDK | 标准工具面 |
| 存储 | SQLite（stdlib sqlite3） | 零运维审计 |
| 前端 | Vue 3 + TypeScript + Vite | 团队熟悉栈 |
| 探针/评测脚本 | Node（原生 WebSocket）+ pytest | 探针已验证模式 |

## 目录与模块边界

见 [architecture.md](architecture.md)。骨架中 `NotImplementedError("Sx")` 标记实现阶段归属。

## 契约冻结清单（双人并行开发的接口边界）

以下文件为跨人契约，修改需双人评审（Gitee PR 双 approve）：

1. `packages/semantic/element.py`（数据模型）
2. `packages/mcp_gateway/server.py` 的 `TOOL_SPECS` 与 `Engine` Protocol
3. `packages/adapters/trae/locators.yaml`（注册表格式）
4. `packages/events/schema.sql`（存储 schema）
5. `docs/api.md`（对外接口）

## 工程纪律

- **fixture-first**：单测不依赖真实 Trae；录制 DOM/UIA 快照放 `tests/fixtures/`；live 测试打 `@pytest.mark.live`，默认排除。
- **状态不靠 sleep**：运行/完成判定必须来自 DOM 信号；固定等待仅允许作为轮询间隔。
- **坐标不跨执行复用**：每次动作前重定位 + 身份核对。
- **失败即停**：探针/集成测试失败超过既定排查路径即停止报告，禁止坐标硬编码绕过。
- 分支：`main` + `feat/a-*`（引擎线）/ `feat/b-*`（产品线）；Gitee PR 合并；合并前跑 `pytest -m "not live"` + `npm run build`。
- 提交信息：`S<阶段>: <动词短语>`（如 `S1: add CDP session attach`）。

## 构建与运行

```bash
python -m pip install -e ".[dev,ocr]"
pytest -m "not live"
pytest -m live            # 需本机 Trae（托管启动带调试端口）
(cd apps/desktop-agent && python -m uvicorn main:app --port 8765)
(cd apps/dashboard && npm install && npm run dev)
(cd apps/dashboard && npm run build)
```

## CI（Gitee Go 或本地钩子，S2 起）

PR 触发：pytest（non-live）+ vue-tsc + vite build；live 与基准评测仅本地手动运行（依赖桌面会话）。
# 架构设计

详见 [PRD.md](PRD.md) §4。本文补充模块边界与关键决策。

## 模块边界

- `perception/*`：只产出带通道证据的原始元素 dict，不做业务判断。CDP 为主通道（Electron），UIA 覆盖原生应用，OCR 补盲，vision 为 P2。
- `semantic/*`：融合结果 → GUIElement；semantic_id 注册表与实时重定位。坐标永不跨执行复用。
- `execution/*`：动作执行（前后快照+后置验证）、安全门、独立验证器。verified 只由 verifier 授予。
- `adapters/*`：业务状态机与通道能力探针；YAML 注册表按 app_version 分节。
- `events/*`：SQLite 审计；所有 MCP 调用与状态迁移留痕。
- `mcp/server.py`：固定 8 工具；Engine Protocol 注入，工具层不含业务逻辑。
- `apps/desktop-agent`：托管启动（loopback 随机调试端口）、审批端点、SSE 事件流。
- `apps/dashboard`：只读展示 + 审批操作。

## 关键决策记录

1. **CDP 优先而非 UIA 优先**：实测 Trae 聊天 WebView 在 UIA 中不可见（PROBE_REPORT F1/F2），CDP 提供全语义（F3）。
2. **CLI chat 降级为候选通道**：3.6.13 静默投递失败（F4）；适配器加载时做通道探针。
3. **读回主通道为 CDP DOM**：回复归档扩展需项目绑定且版本重验（F7），作备通道。
4. **固定工具面**：不随识别元素动态生成 MCP 工具，避免 Agent 上下文臃肿。
5. **三态分离**：submitted / claimed_done / verified 严格区分，界面完成不等于交付完成。
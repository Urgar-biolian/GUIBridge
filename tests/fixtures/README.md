# tests/fixtures 来源说明

| 文件 | 来源 | 可信度 |
|------|------|--------|
| `trae/dom_ide_idle.json` | 按 `probe/PROBE_REPORT.md`「已验证的 Trae 3.6.13 定位器」表**手工构造**的 DOM 快照 | 选择器与状态语义来自实测；rect 数值与文本内容是本机编写的占位，**不是录制数据** |

纪律（docs/framework.md 工程纪律）：

- 这些 fixture 用于 B 线在 G1 门之前驱动状态机与 MCP 单测（fixture-first），**不能**当作 live 出口条件的证据。
- A 线交付 S1 后，`probe/` 与真实录制快照会替换本目录内容；届时 `apps/desktop-agent/simulated.py` 与 `apps/desktop-agent/registry.py` 这两个 G1 前的临时装配件应被删除。
- 任何新增定位器必须先在真实 Trae 3.6.13 上实测并回写 `probe/PROBE_REPORT.md`，再进入 fixture。

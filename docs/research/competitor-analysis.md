# 竞品分析：agent-desktop 与 GUIBridge

状态：Phase 1 公开资料复核（2026-11-17；待 B 线复核）
资料来源：本任务书提供的公开项目地址与公开描述；未读取、未复制、未移植其源代码。公开 README 声明已于 2026-11-17 复核并写入 §2/§3；仍标注“未声明”的条目为公开资料未覆盖项，不得臆测。

## 1. 分析边界

- 允许：阅读公开 README、公开文档、公开技术标准（Windows UIA、MCP、CDP）。
- 禁止：复制、翻译、改写其源代码；复用其内部数据结构或模块划分；将其作为运行时依赖。
- 本文件只做能力层面对比，不评价其实现质量，不引用未公开代码。

## 2. 竞品公开能力概述

以下均为公开 README/仓库元数据**声明**（访问日期 2026-11-17，`github.com/vercel-labs/agent-desktop`，main 分支），非对其实现质量的核实；仅用于能力层面对比，未读取/复制其源代码。

| 维度 | 公开声明 |
|---|---|
| 定位 | “Computer use for AI agents: see and operate desktop apps … through the OS accessibility tree”；“without screenshots or pixel matching”；“agent-desktop has no model inside. The loop lives in your agent.” |
| 感知 | 读取可访问性树并返回 JSON，每个可操作元素带 `ref`；macOS AX API / Windows UI Automation / Linux AT-SPI |
| 平台 | macOS 13+（Intel/Apple Silicon）；Windows 10 1809+（x64/ARM64）；Ubuntu 24.04+（x86_64/aarch64，X11/Wayland） |
| 暴露形式 | CLI + C 库（`libagent_desktop_ffi`）+ MCP over stdio（`agent-desktop mcp`，工具名如 `desktop_snapshot`/`desktop_click`）；自述 61 个命令名、57 个操作命令 |
| 焦点/输入 | “Headless by default. Ref actions use the accessibility API without moving the pointer or taking focus. The global `--headed` flag allows physical input.”；各平台页列出 headless 可用/需 `--headed`/拒绝项 |
| 结果确认 | observe→act→observe 循环；post-action wait 观察 ref 原进程/原窗口；重新 snapshot 校验；JSON 信封 `ok`/`command`/`data` + 错误码（`INVALID_ARGS`/`STALE_REF`/`AMBIGUOUS_TARGET`） |
| 重试纪律 | “Retry a failed command only when `error.disposition.retry` is `safe`.” |
| 隐私 | 快照/剪贴板/截图/命令输出可能含私密桌面内容，要求不入公共日志/上传 |
| 许可证 | Apache-2.0 |

公开 README **未声明**（保持待核实/未公开）：能力感知的多通道路由策略、焦点干扰**检测**与四态结果模型、高影响操作审批令牌模型、AI IDE 专用语义适配、独立代码变更验证证据链（git 范围 + 测试退出码）。

## 3. 能力对比矩阵

竞品列均为公开 README 声明（见 §2，访问 2026-11-17）；本项目列为设计 + 已实测。

| 维度 | agent-desktop（公开声明） | GUIBridge（本项目设计与已实测） |
|---|---|---|
| Windows 感知 | UI Automation（可访问性树→JSON+ref） | UIA + CDP + OCR + 视觉融合；UIA 只读能力已实现（S1） |
| Electron 应用 | 公开资料未声明专用协议 | CDP 实测可读完整 DOM 并完成闭环（F3/F6/F12） |
| 多通道路由 | 公开资料未声明能力感知路由（按平台 adapter + headless/`--headed`） | Capability-Aware Router：按 app×operation 能力表与干扰策略选通道 |
| 焦点/干扰 | 声明 headless 默认“不移动指针/不取焦点”，`--headed` 允许物理输入；未声明干扰**检测** | FocusGuard 实测：本机原生 Win32 UIA 仍引发焦点切换（E1b/E1c），按实测声明 `FOCUS_SWITCH`；前台 HWND/光标/事件钩子监测 + 四态结果 |
| 结果确认 | observe→act→observe + post-action wait + 重新 snapshot；JSON `ok` 信封 | 3 态任务纪律 + 四态 ActionResult + 独立 verifier（git 范围 + 测试退出码） |
| 重试纪律 | 声明仅当 `error.disposition.retry=safe` 才重试 | 原则 6：非幂等 `UNCONFIRMED`/`FAILED` 禁自动重试，由 `decide_retry` 强制 |
| 审批 | 公开资料未声明高影响审批令牌模型（仅 macOS 辅助功能授权引导） | 白名单 + 高影响一次性 token + 手动审批约束 + 路由层 `OperationImpact.HIGH` 审批门 |
| AI IDE 适配 | 公开资料未声明 | Trae 四接口：send/status/read/verify，含前置后置与证据 |
| 暴露形式 | CLI + C 库 + MCP stdio | MCP gateway + CLI（独立实现） |
| 平台范围 | macOS / Windows / Linux | 本期仅 Windows（任务书要求） |
| 许可证 | Apache-2.0 | 独立实现，依赖许可证见 originality-log；不依赖 agent-desktop |
| 运行依赖 | — | 不依赖 agent-desktop；无源码复用 |

**关键差异化（实测支撑，非口头声明）**：竞品公开声明 headless“不取焦点”，但本项目对受控原生靶应用的实测（E1b 后台 9/9、E1c 前台起步 9/9）表明 UIA pattern 调用即便光标零位移仍会切换前台焦点。因此 GUIBridge 不把“无物理鼠标移动”等同于“无焦点干扰”，而是按“应用×操作×控件×前后台状态”实测声明风险，并以 FocusGuard 四态如实报告——这是公开声明未覆盖、且由本机实测驱动的严谨度差异。

## 4. GUIBridge 的差异化定位

1. **能力感知路由而非单一 API 封装**：同一操作在不同应用上可能只有 UIA、专用协议或前台输入可用；Router 显式声明并选择通道。
2. **干扰是一等公民**：每个通道声明干扰风险，FocusGuard 输出四态结果；严格模式禁止未批准的焦点/物理输入。
3. **结果确认与审批闭环**：非幂等操作不自动重试；验证由独立 verifier 完成，不以“界面显示完成”作为成功。
4. **实证驱动的 Trae 适配**：先探针后实现；UIA 对 Electron 不可用的结论来自本机实测，而非假设。

## 5. 相似性与独立性声明

- 相似点：都面向桌面应用语义控制、都使用 Windows UIA、都提供 MCP/CLI 形式的能力暴露。这些属于领域公共技术与公开标准，不构成实现复制。
- 独立点：本项目的能力表、路由策略、FocusGuard 四态、Trae 接口契约、验证链、自修复与 benchmark 均为独立设计；文件结构、数据结构与模块划分独立于竞品。
- 证据：全仓检索无 agent-desktop 引用或依赖；依赖清单见 `docs/research/originality-log.md`。

## 6. 待办（Phase 1）

- [x] 复核 agent-desktop 公开 README 的能力声明，替换“待核实”项（2026-11-17 访问 main 分支 README，§2/§3 已按公开声明更新；未声明者保留标注）。
- [x] 记录其公开许可证与平台要求（Apache-2.0；macOS 13+/Windows 10 1809+/Ubuntu 24.04+；仅用于对比，不引入依赖）。
- [x] 补充“同一任务在三类应用上的通道可用性”实测对比（原生 / Electron / 自绘）：原生 UIA 实测 `focus_switch`（E1b/E1c）、Electron Trae CDP 只读实测 `none`（run `20261117T092712Z`）、自绘靶应用 UIA 无内容语义节点（run `20261117T102927Z` `scan_selfdrawn.py`：仅 3 个非客户区标题栏按钮，`has_edit=false`、`content_button_count=0`，OCR/视觉仅定位）。三类负例/正例均入能力表草案。
- [ ] 由 B 线复核本文件，确认无未授权源码引用、公开声明引用准确。

## 7. 来源

- 任务书提供的项目地址：https://github.com/vercel-labs/agent-desktop （公开 README + 仓库元数据，访问 2026-11-17，main 分支；引用章节：Install / Quick start / How it works / For AI agents / MCP / Commands / Platform support / C library / License）。仅读取公开 README 与元数据做能力对比，未读取/复制/移植其源代码。
- Windows UI Automation 官方文档
- MCP 官方规范
- Chrome DevTools Protocol 官方文档

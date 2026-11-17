# 竞品分析：agent-desktop 与 GUIBridge

状态：Phase 0 骨架（2026-11-17）
资料来源：本任务书提供的公开项目地址与公开描述；未读取、未复制、未移植其源代码。标注“待核实”的条目必须在 Phase 1 通过公开文档复核后才能写入结论。

## 1. 分析边界

- 允许：阅读公开 README、公开文档、公开技术标准（Windows UIA、MCP、CDP）。
- 禁止：复制、翻译、改写其源代码；复用其内部数据结构或模块划分；将其作为运行时依赖。
- 本文件只做能力层面对比，不评价其实现质量，不引用未公开代码。

## 2. 竞品公开能力概述

根据公开描述，agent-desktop 读取桌面应用控件并暴露操作能力：

| 维度 | 公开描述 |
|---|---|
| 感知 | Windows UI Automation、macOS Accessibility API、Linux AT-SPI |
| 操作 | 通过 CLI、MCP 等方式提供操作能力 |
| 平台 | Windows / macOS / Linux |

以下内容公开资料未明确，标记待核实：执行通道路由策略、焦点干扰检测、操作结果四态、审批模型、AI IDE 专用适配、验证证据链、许可证细节。

## 3. 能力对比矩阵

| 维度 | agent-desktop（公开资料） | GUIBridge（本项目设计与已实测） |
|---|---|---|
| Windows 感知 | UIA | UIA + CDP + OCR + 视觉融合；UIA 只读能力已实现（S1） |
| Electron 应用 | 公开资料未声明专用协议 | CDP 实测可读完整 DOM 并完成闭环（F3/F6/F12） |
| 多通道 | 公开资料未声明路由 | Capability-Aware Router：按 app×operation 能力表与干扰策略选通道 |
| 干扰检测 | 公开资料未声明 | FocusGuard：前台 HWND、光标、目标激活、四态结果 |
| 结果确认 | 公开资料未声明 | 3 态任务纪律 + verifier（git 范围 + 测试退出码） |
| 审批 | 公开资料未声明 | 白名单 + 高影响一次性 token + 手动审批约束 |
| AI IDE 适配 | 公开资料未声明 | Trae 四接口：send/status/read/verify，含前置后置与证据 |
| 平台范围 | 三平台 | 本期仅 Windows（任务书要求） |
| 运行依赖 | — | 不依赖 agent-desktop；无源码复用 |

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

- [ ] 复核 agent-desktop 公开 README 的能力声明，替换“待核实”项。
- [ ] 记录其公开许可证与平台要求（仅用于对比，不引入依赖）。
- [ ] 补充一张“同一任务在三类应用上的通道可用性”实测对比（原生 / Electron / 自绘）。
- [ ] 由 B 线复核本文件，确认无未授权源码引用。

## 7. 来源

- 任务书提供的项目地址：https://github.com/vercel-labs/agent-desktop
- Windows UI Automation 官方文档
- MCP 官方规范
- Chrome DevTools Protocol 官方文档

# GUIBridge 第一阶段技术验证报告（Go/No-Go）

日期：2026-11-17｜环境：Windows 11 26100（多显示器）｜Trae 3.6.13（CLI 1.107.1，`D:\Program\Trae`）｜Python 3.12.9｜Node 22.12.0

## 结论：GO，但技术路线修正为「CDP 优先、UIA 次之、OCR 兜底」

原方案假设 UIA 优先。实测否定了该假设对 Electron 目标（Trae）的适用性，同时发现了一条更强的语义通道（CDP）。闭环已端到端验证。

## 发现与证据

| # | 发现 | 证据 |
|---|------|------|
| F1 | UIA 默认只暴露 17 个节点（窗口框架级），聊天 WebView 内容完全不可见 | `uia_probe.py` 首跑；`uia_dump.json` |
| F2 | 加 `--force-renderer-accessibility` 重启后升到 62 节点，出现 `ai-agent-chat-history-container` 等 AutomationId，但聊天输入框/发送按钮仍不在 UIA 树中 | `uia_probe.py` 二跑；`uia_dump.json` |
| F3 | **CDP（`--remote-debugging-port=9222`）可读取聊天面板完整 DOM 语义**：输入框、发送按钮（含 disabled 状态类）、模型选择、审批模式、模式入口，均有稳定 class/role/aria-label/data-testid | `cdp_probe.mjs` 输出 |
| F4 | `trae chat --mode ask --reuse-window` 退出码 0 但消息不进入可见会话（SOLO 与 IDE 模式均复现）——**CLI chat 通道在本版本不可靠** | `cli_chat.log`（EXIT=0）+ 发送前后 DOM 对比（任务数始终 0） |
| F5 | SOLO 模式无 Chat/Ask 模式（模式菜单是智能体选择器）；Chat 模式在 IDE 模式：顶栏分段控件 `.icube-mode-tab-item-ide` 切换，模式菜单 `.popup-menu` 内叶子项 `Chat` | `cdp_mode_menu.mjs`、`cdp_titlebar.mjs`、`cdp_send_test.mjs` |
| F6 | **提交→状态→读回闭环成立**：CDP focus 输入框 → `Input.insertText` → 点击 `.chat-input-v2-send-button` → 运行态出现「思考中」文本 → 完成后 DOM 读回助手回复 `OK` | `cdp_send_test.mjs`、`cdp_readback.mjs` 输出 |
| F7 | 回复归档扩展 `local-tools.trae-reply-reader` 已安装但固定在其他项目（demo/liangguan），心跳停于 2026-10；对本项目无归档。CDP DOM 读回可替代该扩展 | `trae_replies.py status`；globalStorage status.json |
| F8 | 多显示器真实风险实证：探针期间 Trae 窗口被移到第二显示器 (2796,-289)，固定坐标截图失效 | 窗口枚举输出；`trae_after_send.png` 截到错误窗口 |
| F9 | 测试消息实际以 Agent 模式+自动审批发送（模式菜单误点父容器）。模型仅回复 OK，工作区文件零变更（已核对）。**适配器必须把审批模式强制为手动，除非用户显式授权** | `cdp_send_test.mjs` 日志；`find . -type f` 核对 |

## 已验证的 Trae 3.6.13 定位器（IDE 模式）

| 语义 ID | 定位器 | 备注 |
|---------|--------|------|
| `trae.mode.ide_tab` | `.icube-mode-tab-item-ide` | 顶栏分段控件，点击父级 item |
| `trae.chat.mode_entry` | `.v2-agent-entry-btn` | 菜单为 `.popup-menu`，选叶子项文本精确匹配 |
| `trae.chat.composer` | `.chat-input-v2-input-box-editable` | `div[role=textbox][contenteditable=true]` |
| `trae.chat.send_button` | `.chat-input-v2-send-button` | `disabled` 类 = 空输入；提交验证信号之一 |
| `trae.chat.approval_mode` | `button[aria-label=自动审批]`（`.permissionModeTrigger-*`） | 安全关键控件 |
| `trae.chat.model_select` | `.icd-model-select-trigger` | role=combobox |
| `trae.chat.new_session` | `[data-testid=ai-chat-create-new-session]` | |
| `trae.chat.running_state` | 会话容器 innerText 含「思考中/生成中/运行中」 | 文本级状态信号 |
| `trae.chat.conversation` | `.ai-chat-v2-ide-root` innerText | 读回通道 |

## 通道能力矩阵（修正后的感知分层依据）

| 通道 | 覆盖 | 前提 | 可靠性 |
|------|------|------|--------|
| CDP DOM | Electron/Chromium 应用全语义 | 托管启动注入 `--remote-debugging-port`（loopback） | 高（本实测） |
| UIA | 原生 Win32/WPF/WinForms；Electron 仅框架级 | 无需注入；Electron 需 accessibility 开关仍不完整 | 原生高 / Electron 低 |
| OCR | 任意可见像素文本 | 无 | 中（兜底） |
| Trae CLI chat | 任务提交 | 版本敏感 | 本版本不可靠，仅候选 |
| 回复归档扩展 | 助手回复落盘 | 扩展安装+项目绑定 | 旧版本验证过，需重验 |

## 未验证项（转入开发阶段首批任务）

1. 窗口移动/缩放/DPI 变化后 CDP 定位器稳定性（CDP 用 DOM 坐标，预期免疫，需实测）。
2. Agent 模式长任务的状态机（运行/工具调用/待审批/完成/失败）完整观测。
3. 手动审批模式下待审批信号的 DOM 特征。
4. Trae 版本升级后选择器漂移与自修复流程。
5. Qoder Sites 对演示站点的后端/实时连接限制。

## 安全备注

- CDP 端口无认证：仅绑定 127.0.0.1、每会话随机端口、进程退出即关闭；写入 `docs/security.md`。
- 探针脚本与截图含本机界面信息，仅存本地 `probe/`，不上传。
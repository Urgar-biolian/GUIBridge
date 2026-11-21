# 原创性与依赖记录（Originality Log）

状态：Phase 0 初稿（2026-11-17）
维护规则：每次引入新依赖、新算法或参考新公开资料时追加条目；契约与结论由 A/B 双人复核。本文件不替代许可证原文；完整依赖审计已于 2026-11-21 完成，结论与逐包清单见 [docs/licenses.md](../licenses.md)。

## 1. 属于公共技术原理的部分

以下内容来自 Windows/Web 公共平台能力或公开标准，任何同类项目均可使用，不主张原创：

| 原理 | 用途 | 依据 |
|---|---|---|
| Windows UI Automation（UIA）pattern（Invoke/Value/Toggle/Text） | 原生控件语义读取与操作 | Microsoft 官方文档 |
| MSAA → UIA 桥 | 标准 Win32 控件的可访问性暴露 | Microsoft 官方文档 |
| Win32 前台窗口/光标 API（GetForegroundWindow/GetCursorPos/SetWinEventHook） | FocusGuard 监测 | Microsoft 官方文档 |
| SendInput / SetCursorPos / keybd_event | 前台输入基线对照 | Microsoft 官方文档 |
| Chrome DevTools Protocol（Runtime.evaluate、Input.insertText、Input.dispatchMouseEvent） | Electron 应用语义通道 | CDP 官方文档 |
| MCP（Model Context Protocol） | 工具能力暴露 | MCP 官方规范 |
| OCR（RapidOCR/ONNX Runtime） | 无控件语义时的视觉兜底 | 公开项目文档 |
| SQLite WAL、append-only 事件表 | 事件存储 | SQLite 官方文档 |
| Windows 窗口消息（WM_CHAR/WM_SETTEXT 等） | 后台消息注入可行性研究 | Microsoft 官方文档 |

## 2. 参考了公开研究/公开资料的部分

| 内容 | 参考来源 | 使用方式 |
|---|---|---|
| 竞品能力边界 | agent-desktop 公开 README/公开描述 | 仅做能力对比；未读取或复制源代码 |
| UIA 模式语义 | Microsoft UIA 文档 | 按文档实现 pattern 调用 |
| CDP 附着与求值 | CDP 文档 + 本项目探针实测 | 独立实现 `packages/perception/cdp.py` |
| MCP 工具定义 | MCP 规范 | 独立实现 `packages/mcp_gateway/server.py` |
| 桌面自动化干扰风险 | 公开讨论与 Windows 输入模型 | 形成 FocusGuard 四态设计 |

## 3. 本项目独立设计（含证据）

| 设计 | 说明 | 证据 |
|---|---|---|
| 实证驱动的通道选择 | 先探针后实现；Electron 目标改用 CDP，而非假设 UIA 普适 | `src/probe/PROBE_REPORT.md` F1–F12；S0 `fdde728` |
| 3 态任务纪律 | `submitted ≠ claimed_done ≠ verified`；verified 仅由独立验证器给出 | S2 `ce2e37b`；S3 `80886e3` |
| claimed_done 判据 | “曾 running、现空闲、无审批提示”；unknown 180s 抑制 | `packages/adapters/trae/adapter.py`；F12 |
| 自修复与歧义停止 | hint 重扫、唯一候选、复验、pending 补丁；歧义 100% 停止 | S4-a `c92f3b4` |
| 独立验证器 | 隔离 worktree + `allowed_files` 范围 + 测试退出码 | `packages/execution/verifier.py`；S3 |
| A/B/C benchmark 与负例 | 坐标回放 / 无语义验证 / 语义+后置验证；禁用目标负例 | `tests/bench/`；S5 `0f1a4d5` |
| Capability-Aware Router | app×operation 能力表 + 干扰策略 + 通道降级 | `guibridge-design.md` §3；Phase 0 草案 |
| FocusGuard 四态 | 成功/成功但干扰/失败/无法确认；“未观察”不等于“无干扰” | `guibridge-design.md` §4；Phase 0 草案 |
| Trae 四接口契约 | 前置/步骤/后置/证据；回复文本一律不可信 | `guibridge-design.md` §5；S2/S3 实现 |

## 4. 与竞品存在相似性的部分

| 相似点 | 性质 | 说明 |
|---|---|---|
| 使用 Windows UIA 读取/操作控件 | 领域公共技术 | 标准 API，非竞品专有 |
| 通过 MCP/CLI 暴露能力 | 公开标准 | MCP 为公开规范 |
| 桌面应用自动化 | 领域问题 | 目标相同不等于实现相同 |
| 跨平台可访问性思路 | 公共研究 | 本项目本期仅 Windows，未移植竞品代码 |

独立性证据：

- 全仓检索无 `agent-desktop` / `vercel-labs` 代码引用或运行时依赖。
- 目录结构、数据模型与模块划分独立设计（`packages/perception|semantic|adapters|execution|routing|focusguard`）。
- 探针、适配器、验证器、benchmark 均在本仓库按实测独立实现。

## 5. 第三方依赖与许可证（已核验版本）

> 权威清单（含传递依赖、缺口与 mcp 版本偏差）见 [docs/licenses.md](../licenses.md)；下表按 2026-11-21 的 `.venv` 取数。

### Python（`pyproject.toml`，本机元数据核验）

| 依赖 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| uiautomation | 2.0.29 | Apache-2.0 | UIA 访问 |
| mss | 10.2.0 | MIT | 截图 |
| PyYAML | 6.0.3 | MIT | 定位器配置 |
| websockets | 17.4 | BSD-3-Clause | CDP 连接 |
| FastAPI | 0.163.1 | MIT | 桌面代理 API |
| Uvicorn | 0.54.0 | BSD-3-Clause | ASGI 服务 |
| mcp | 2.3.0（声明 `>=1.0,<2`） | MIT | MCP 服务端 |
| Pillow | 13.0.0 | MIT-CMU | gbdash / Python 镜像截图与显示 |
| rapidocr-onnxruntime | 未安装 | — | OCR（可选，未审计） |
| pytest | 9.2.0 | MIT | 测试 |

### 前端（`apps/dashboard`，本机 node_modules 元数据核验）

| 依赖 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| vue | 3.5.45 | MIT | Dashboard |
| vite | 6.4.6 | MIT | 构建 |
| typescript | 5.6.3 | Apache-2.0 | 类型检查 |
| vue-tsc | 2.2.12 | MIT | 类型检查 |
| @vitejs/plugin-vue | 5.2.4 | MIT | Vue 构建插件 |

### 待办

- [x] 审计传递依赖（Python 43 个第三方发行版全部为宽松许可，含 Pillow MIT-CMU；OCR 闭包由 A 线审计覆盖，本机未安装未复跑）。
- [x] 审计前端传递依赖许可证（50 个包，全 MIT/ISC/BSD/Apache-2.0）。
- [x] 生成完整依赖清单（`docs/licenses.md`，按本机 `.venv` 与 `node_modules` 取数；无锁定文件）。
- [ ] OCR 通道如启用，安装 `ocr` extra 后补审 onnxruntime/opencv 闭包与模型许可。
- [ ] 所有新增依赖先登记后引入。

## 6. 变更记录

| 日期 | 变更 | 复核 |
|---|---|---|
| 2026-11-17 | Phase 0 初稿：公共原理、独立设计、相似性、依赖许可证 | 待 B 线复核 |
| 2026-11-17 | 复核 agent-desktop 公开 README（Apache-2.0、三平台 AX/UIA/AT-SPI、CLI+C 库+MCP、headless 声明、`error.disposition.retry` 重试纪律），更新 competitor-analysis §2/§3；修正 §3 交叉引用指向 `guibridge-design.md` §3/§4/§5；仅公开资料，无源码引用 | 待 B 线复核 |
| 2026-11-21 | 收尾：完成依赖许可证审计并落 `docs/licenses.md`；项目许可定为 MIT，新增根目录 `LICENSE` | 待 B 线复核 |

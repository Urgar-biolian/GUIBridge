# API 规范

两套接口：MCP 工具面（Agent 调用）与本地 REST/SSE（Dashboard 与审批）。
实现阶段：S2。契约冻结清单见 [framework.md](framework.md)。

## 1. MCP 工具（固定 8 个）

通用输出约定：所有结果附 `evidence: string[]`（事件/快照 ID）；`confidence` 附 `calibrated=false`；读回文本附 `untrusted=true`。

### gui.list_windows
输入 `{}`；输出 `{windows: [{window_id, process_name, title, bounds, whitelisted}]}`。

### gui.inspect_window
输入 `{window_id: string, max_depth?: int=18}`；输出 `{elements: GUIElement[]}`（融合后，含 source/confidence/evidence）。

### gui.find_element
输入 `{window_id, semantic_id?, role?, name?}`；输出 `{elements: GUIElement[]}`；无匹配返回空数组而非报错。

### gui.perform_action
输入 `{window_id, semantic_id, action: "click"|"type"|"select"|"invoke", args?: object, approval_token?: string}`。
输出 `ActionResult {success, verified, error_code?, before_snapshot_id, after_snapshot_id, evidence}`。
高影响语义 ID（approval_mode/terminal/delete/install/git_*）缺 token → `approval_required`。

### gui.get_snapshot
输入 `{window_id}`；输出 `{snapshot_id, ts, elements_summary, image_path}`。

### trae.send_task
输入 `{project_path, task, mode?: "chat"|"agent"="chat", allow_files?: string[], acceptance?: {test_commands: string[]}}`。
输出 `TaskRecord`；agent 模式无审批授权 → `approval_required`；默认强制手动审批。

### trae.get_status
输入 `{task_id}`；输出 `{task_id, state, signals: {running_text?, stop_control?, approval_prompt?}, evidence}`；信号冲突 → state=unknown。

### trae.read_result
输入 `{task_id, max_chars?=8000}`；输出 `{task_id, reply_text, untrusted: true, claimed_done: bool, evidence}`；截断显式标注。

### 错误码

| code | 含义 |
|------|------|
| locator_missing | 重定位全链失败 |
| conflict | 多通道/多候选冲突，停止执行 |
| approval_required | 高影响动作缺审批 |
| not_submitted | 发送后置验证失败 |
| unknown_state | 状态信号冲突/超时 |
| window_not_allowed | 窗口不在白名单 |
| identity_mismatch | 动作前窗口/进程/元素身份核对失败 |

## 2. 本地 REST（desktop-agent，127.0.0.1:8765）

仅 loopback；Dashboard 经 Vite 代理 `/api` → 本服务（rewrite 去前缀）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 存活与阶段 |
| GET | /windows | 白名单窗口 |
| POST | /windows/{window_id}/whitelist | 用户显式加入白名单 |
| GET | /windows/{window_id}/snapshot | 快照 |
| GET | /tasks | 任务列表 |
| POST | /tasks | 等价 trae.send_task |
| GET | /tasks/{task_id} | TaskRecord + 迁移链 |
| GET | /tasks/{task_id}/result | 等价 trae.read_result |
| GET | /approvals/pending | 待审批请求 |
| POST | /approvals | 授予审批（返回一次性 token） |
| GET | /events | SSE 事件流（Dashboard 回放） |
| GET | /locators | 注册表 |
| POST | /locators/{semantic_id}/heal-review | 审核 heal_patches（approve/reject） |

错误信封：`{error_code, message, evidence}`；HTTP 状态与 MCP 错误码一一映射（approval_required→403，conflict→409，unknown_state→424，其余 4xx/5xx 按语义）。

## 3. 通道内部接口（非对外 API）

`perception/*` 输出原始元素 dict；`semantic.resolver` 消费 Locator.chain；CDP 客户端响应层级为 `msg.result.result.value`（探针实测陷阱，见 PROBE_REPORT）。
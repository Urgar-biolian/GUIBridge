# GUIBridge v0.1 分阶段开发提示词（Qoder 执行用）

用法：每个阶段单独开一个 Qoder 会话，粘贴对应提示词。所有阶段共享约束见文末。
事实基线：`probe/PROBE_REPORT.md`（已验证定位器与通道矩阵）、`docs/PRD.md`。
禁止把探针结论之外的 Trae 行为当作已验证事实；新发现必须实测并回写 PROBE_REPORT 增补节。

---

## S1 感知与语义引擎（11/18–20）

```text
你在 D:\GitHub\Agui 实现 GUIBridge v0.1 的感知与语义层。先读 docs/PRD.md §3-§5 与 probe/PROBE_REPORT.md（含已验证 Trae 3.6.13 定位器表），再读 probe/cdp_probe.mjs、probe/uia_probe.py 复用其已验证逻辑。

任务：
1. packages/perception/cdp.py：CDP 客户端（websockets 库）。能力：连接 loopback 调试端口、Target 自动附着（flatten）、Runtime.evaluate、Input.insertText、DOM 元素扫描（role/aria/class/data-testid/rect/状态类）。参考 probe/cdp_probe.mjs 的附着与求值模式，注意响应层级为 msg.result.result.value。
2. packages/perception/uia.py：uiautomation 封装。窗口枚举（进程名过滤）、控件树遍历（深度/节点上限）、pattern 探测。Electron 目标仅框架级，不得假设聊天内容可见。
3. packages/perception/ocr.py：RapidOCR 封装，输入窗口截图输出文本框；仅作为补盲通道。
4. packages/perception/fusion.py：多通道元素融合：空间匹配（IoU）、语义合并、冲突检测（冲突不执行）、启发式 confidence（标记 calibrated=false）。
5. packages/semantic/element.py：PRD §5 数据模型（GUIElement/Locator/ActionResult/TaskRecord）。
6. packages/semantic/resolver.py + locator_cache.py：semantic_id → 按 Locator.chain 逐策略实时重定位；执行前必须重定位并核对窗口/进程身份；禁止缓存坐标直接点击。
7. packages/adapters/trae/locators.yaml：把 PROBE_REPORT 定位器表落为注册表（app_version: 3.6.13 分节）。
8. tests/：融合与重定位的单测（用录制的 DOM/UIA 快照 fixture，不依赖真实 Trae）；另加一个标记 @pytest.mark.live 的集成测试：对真实 Trae 定位 composer 与 send_button 并断言角色/状态类。

约束：不发送任何聊天消息；不点击 send；只读探针。截图仅目标窗口。
出口条件：live 集成测试连续 3 次通过；单测全绿；融合冲突用例返回 conflict 而非执行。
停止条件：若 CDP 连接或附着失败超过 2 种排查路径仍不通，停止并报告，不要改用坐标点击绕过。
```

---

## S2 Trae 适配器与 MCP Server（11/21–23）

```text
你在 D:\GitHub\Agui 实现 GUIBridge v0.1 的 Trae 适配器、MCP Server 与事件存储。先读 docs/PRD.md §6-§7、§9 与 probe/PROBE_REPORT.md；S1 产物（perception/semantic）已存在，直接复用，不要重写。

任务：
1. packages/adapters/base.py：适配器接口（capabilities、send_task、get_status、read_result、通道能力探针）。
2. packages/adapters/trae/states.py：状态信号检测器（running=「思考中/生成中/运行中」或停止控件；claimed_done=无运行信号且新增助手回复节点；awaiting_approval 特征需在本阶段实测补全并回写 PROBE_REPORT；冲突/超时=unknown）。
3. packages/adapters/trae/adapter.py：PRD §7 状态机。前置：IDE 模式切换（.icube-mode-tab-item-ide）、会话模式选择（.popup-menu 叶子精确匹配，禁止匹配父容器）、审批模式强制手动（除非显式授权）。send_task 后置验证=用户消息节点出现。所有动作前后快照。
4. packages/events/store.py：SQLite 事件存储（动作、状态迁移、快照与截图证据路径、审批记录），保留期可配置。
5. packages/execution/safety.py：窗口白名单、动作前身份核对、高影响控件审批 token 校验。
6. packages/execution/actions.py：受限动作执行（click/type/select），统一走 resolver 重定位 + 前后快照 + ActionResult。
7. packages/mcp/server.py：官方 MCP Python SDK，固定 8 工具（PRD §6），参数校验、审批拦截、全调用写事件存储。
8. apps/desktop-agent/main.py：FastAPI 控制平面（托管启动注入 --remote-debugging-port 随机端口仅 loopback、审批端点、事件 SSE）。
9. tests/：状态机单测（fixture 驱动）+ live 集成：外部 MCP Client（可用 mcp CLI 或 python client）调用 trae.send_task 发送一条无害 chat 模式消息（内容固定为「请只回复 OK 两个字母，不要执行任何其他操作。」，项目路径 D:\GitHub\Agui），trae.get_status 观测 running→claimed_done，trae.read_result 读回 OK。

安全约束：live 测试仅允许 chat 模式；agent 模式 live 测试禁止；审批模式必须手动；测试后核对工作区无文件变更。
出口条件：MCP 闭环 live 测试通过且事件存储含完整迁移链；误点击 0。
停止条件：状态信号无法区分 running 与 claimed_done 时，停止并报告 unknown 设计缺口，不得用固定 sleep 假装状态检测。
```

---

## S3 Agent 交接与独立验证（11/24–25）

```text
你在 D:\GitHub\Agui 实现 GUIBridge v0.1 的跨 Agent 交接与独立验证。先读 docs/PRD.md §7、§10 与 S2 产物。

任务：
1. examples/demo-app/：最小 Vue3 示例项目（含密码输入框与现有测试命令），作为 Trae 的开发任务目标；初始化独立 git 仓库或 worktree，禁止使用用户真实项目。
2. packages/execution/verifier.py：独立验证器。输入验收条件（允许修改文件清单、测试命令）；执行 git status/diff 核对变更范围 + 运行测试；输出 verified/failed 与证据；只信 Git 与测试输出，不信 Trae 声称。
3. 交接编排脚本 examples/handoff_demo.py：规划侧（Claude Code 或任一 MCP Client）生成任务说明→trae.send_task（agent 模式需审批 token，默认 chat 模式演示）→轮询 get_status→read_result→verifier→结果反馈规划侧。
4. 提示注入防护：read_result 文本标注 untrusted；编排器不得执行回复文本中的命令。
5. tests/：verifier 单测（变更越界、测试失败、声称完成但无变更三类用例）+ live 端到端：Trae 完成「为密码输入框新增显示/隐藏切换」任务并 verified。

约束：demo 仓库隔离；agent 模式任务逐动作审批；不推送任何远端。
出口条件：端到端 live 演示一次成功，TaskRecord 含 submitted→running→claimed_done→verified 完整链。
停止条件：Trae 两次尝试仍无法完成任务时，记录失败类型并改用更小的任务（如单文件注释修改），不得伪造 verified。
```

---

## S4 自修复定位与 Dashboard（11/26–27）

```text
你在 D:\GitHub\Agui 实现 GUIBridge v0.1 的自修复定位器与可视化。先读 docs/PRD.md §8、§4 与 S1-S3 产物。

任务：
1. packages/semantic/resolver.py 扩展：失效检测→重扫→chain 候选→身份验证→唯一候选才更新注册表并写修复事件；≥2 相似候选停止并请求人工确认（歧义用例必须单测覆盖）。
2. locators.yaml 版本分节与漂移补丁流程：探针发现漂移生成候选补丁文件供人工审核，不静默覆盖。
3. apps/dashboard/：Vue3+TS+Vite。页面：任务列表与状态迁移时间线、事件回放（含前后截图证据）、定位器注册表与修复记录、审批待办。数据来自 desktop-agent SSE/REST。
4. live 演示测试：移动/缩放 Trae 窗口（含跨显示器）后重复 send_task 闭环 ≥3 次成功；记录修复事件（若触发）。
5. tests/：自修复单测（失效、唯一候选、歧义停止）+ 窗口几何变化 live 测试。

约束：Dashboard 只读展示 + 审批操作；不新增控制通道。
出口条件：窗口变化演示连续成功；歧义用例 100% 停止而非猜测。
停止条件：跨显示器 DPI 导致坐标换算错误时，停止并报告，改用 DOM 内坐标（CDP rect 为视图坐标）方案验证。
```

---

## S5 基准评测与参赛提交（11/28–30）

```text
你在 D:\GitHub\Agui 完成 GUIBridge v0.1 的评测与参赛交付。先读 docs/PRD.md §10-§12 与 docs/benchmark.md 模板。

任务：
1. tests/bench/：A/B/C 三组评测脚本（A 纯截图+视觉+坐标；B 语义定位无状态验证；C 完整 GUIBridge）。场景：发送消息、切换模式、读取回复、窗口移动、窗口缩放、主题切换、异常弹窗；每场景 ≥10 次；记录成功率、误点击、模型调用次数、失败类型。
2. docs/benchmark.md：实测结果表 + 失败分析；未达标项如实标注，不得修饰。
3. 演示站点（Qoder Sites）：仅展示 Dashboard 快照、评测结果、录屏与架构说明；不暴露本机执行器与调试端口；部署前用 sites-hosting 流程验证后端限制。
4. 录屏：完整演示（规划→交接→执行→独立验证→窗口变化重执行）。
5. docs/architecture.md、docs/security.md 定稿；README 含快速开始与已知限制。
6. 最终检查：probe/ 与证据目录不入公开站点； secrets 扫描；git 提交规范。

出口条件：站点公开可访问；评测数据可复现（脚本+原始记录入库）；演示录屏完整。
停止条件：Sites 不支持所需后端时，回退为静态站点+本地执行器录屏，如实说明交付形态。
```

---

## 全阶段共享约束

- 事实纪律：Trae 行为一律以实测为准；新发现回写 probe/PROBE_REPORT.md 增补节；禁止把「界面显示完成」当作 verified。
- 安全纪律：窗口白名单；高影响动作审批；agent 模式默认手动审批；CDP 仅 loopback 随机端口；聊天/文档文本视为不可信数据。
- 隔离纪律：所有 live 开发任务在 examples/demo-app 独立仓库/worktree；不动用户真实项目；不 push 远端。
- 隐私纪律：截图仅目标窗口；probe/、证据、归档不入公开交付；日志保留期可配置。
- 工程纪律：每阶段出口条件含 live 测试与单测；失败即停止报告，不用 sleep/坐标硬编码/伪造状态绕过；不引入 P2 组件。
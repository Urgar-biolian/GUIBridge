# 开发进度与双人并行计划（任务书对齐版）

基线日期：2026-11-17｜交付窗口：11/18–30
本文件替代旧版进度表；旧版把 S3/S5 标为未开始，与仓库实际不符，已修正。

## 1. 当前真实进度

分支 `feat/a-perception`，Phase 1 契约验证补强已完成并推送（具体提交/run 见下表证据列），工作树干净，已与远端一致。

| 阶段 | 状态 | 证据 |
|---|---|---|
| S0 技术探针 | 完成 | `src/probe/PROBE_REPORT.md` F1–F12；GO，CDP 优先；提交 `fdde728` |
| 方案评审 | 完成 | 外部引用 5/5 属实；3 处判断修正 |
| PRD / 开发提示词 | 完成 | `docs/PRD.md`、`docs/dev-prompts.md` |
| 项目骨架 | 完成 | 单测通过；模块可导入；Dashboard 构建通过 |
| 契约与文档 | 完成（旧契约） | `element.py` / Engine Protocol / `locators.yaml` / `schema.sql` / `api.md` |
| S1 感知与语义 | 完成 | `0e46c61`；单测 32；live 只读定位 3 连过 |
| S2 适配器与 MCP | 完成 | `ce2e37b`；单测 83；live MCP 闭环读回 OK，工作区零变更 |
| S3 交接与验证 | 完成 | `80886e3`；verifier + 隔离 demo + 模拟执行链；live agent 模式受安全约束未执行 |
| S4-a 自修复 | 完成 | `c92f3b4`；歧义停止单测；live 3 轮通过 |
| S4-b Dashboard | 完成（降级为可选展示） | `1ecf972`；浏览器实测通过 |
| S5 基准与提交 | 完成（DOM fixture 基准） | `0f1a4d5`；A/B/C 原始 JSON + benchmark 文档；站点/录屏未发布 |
| Phase 0 任务书对齐 | 完成（G0 待 B 线 approve） | `2665660`；四份文档 + `src/probe` 迁移 + 契约草案；102 测试通过 / 1 跳过 |
| Phase 1 E1–E6 实验 | 完成（验收已补齐，DPI 保留） | `30378b2`；runner + 原始 JSON；权威 run `20261117T082451Z`；E1b 9/9 光标零位移但 9/9 焦点切换；E4 DPI 未执行 |
| Phase 1 P0 增补 | 完成（待 B 线 approve 契约） | `4665ab8`；run `20261117T090104Z`；E1c 前台 9/9 瞬时焦点切换（钩子补捉轮询漏掉的 3 次）；E2 停留曲线 57–138 ms 轮询/钩子 9/9、误报 0/3；微信可见窗口仅 4 UIA 节点；Trae 授权 live Chat 读回 `OK`、工作区零变更；四态单测 6 例；契约评审包见设计文档第 11 节 |
| Phase 1 契约验证补强 | 完成 | `776aae6`/`3526683`；路由契约单测 18 例 + 焦点聚合/精确计时单测；`dwell_limit.py` run `20261117T091848Z`/`093513Z` 25/25 检出，系统 event_time 精确最短停留 15 ms（<2 ms 盲区）；实测能力表草案 + 加载器 + 7 例单测；`trae_cdp_focus.py` run `20261117T092712Z` 只读 CDP 5/5 无干扰→只读接口 none，send_task 仍 unknown 待重新授权；`focusguard_reliability.py` run `20261117T093120Z` 误报 0/30、检出 15/15；重试策略草案 `retry_policy.py`（原则 6 落地）+ 11 例单测；操作影响维度 `OperationImpact` + 审批门（原则 7 落地）+ 25 例单测；草案契约组合单测 5 例（路由→分类→重试贯通）+ 能力表完整性守护 4 例；`classify()` 修正使 `UNCONFIRMED` 可达（缺正面确认≠确定失败）、探针 UIA 风险硬编码改为实测 `FOCUS_SWITCH`（run `20261117T100205Z` 3/3 实测确认）；四态→冻结信封桥接草案 `legacy_bridge.py` + 8 例单测；UIA 形式化通道 `UiaPatternChannel` 注入式草案实现 + 12 例单测（未接入冻结执行器）；自绘靶应用负例 `scan_selfdrawn.py` run `20261117T102927Z`（内容无 UIA 语义，仅标题栏 chrome 按钮）入能力表草案 + 1 例路由单测；Trae 适配器（能力 C）安全前置/回复提取纯逻辑 16 例单测（agent 未批准拒绝、非法模式拒绝、`extract_last_reply` 边界，均在 CDP/store 前触发，无 live 写）；正式 `TraeAdapter` 读路径 `verify_trae_adapter_read.py` run `20261117T112436Z` 真实只读实测 5/5 none、probe_channels 与能力表一致（无 live 写、仅录长度/布尔）；独立验证器不可运行/超时测试命令必判失败 3 例单测；能力表完整性守护新增写操作禁 OCR_VISION 后台执行 1 例（原则 3，路由层强制见 R6）；R2 选项 (a) 扩展信封候选 `extended_envelope.py` + 7 例单测（未改冻结 api.md）；R4 选项 (b) 操作名 crosswalk 候选 `operation_names.py` + 8 例单测（漂移守护，未改冻结 TOOL_SPECS）；R3 选项 (a) 外部输入归因候选 `attribution.py` + 12 例单测（污染降级，FOREGROUND_INPUT 豁免）；R6 选项 (a) OCR 感知路由候选 `ocr_guard.py` + 7 例单测（写排除/读保留）（共 269 通过）；B 线裁决清单 R1–R6（设计文档 11.5，区别于本表 D1–D7 历史决策）+ 草案契约链实测探针 `verify_contract_chain.py` run `20261117T101352Z`（路由→分类→重试→桥接 3/3 贯通）+ 决策候选实测探针 `verify_decision_candidates.py` run `20261117T111617Z`（R2/R3/R4/R6 四候选落到真实测量数据，5/5 检查；invoke 窗口真实外部输入污染触发 R3 降级 UNCONFIRMED，非仅合成） |

## 2. 任务书对齐后的范围调整

- 现有 S1–S5 定位为**预研原型资产**，不作为参赛交付基线。
- 新增 Phase 0（规划与骨架）与 Phase 1（独立可行性验证），优先补齐任务书验收。
- Dashboard 不再是 Phase 1 优先项；`engine` / `mcp_gateway` / Dashboard 在 Phase 1 冻结。
- 新交付：`docs/research/competitor-analysis.md`、`docs/research/originality-log.md`、`docs/architecture/guibridge-design.md`、`docs/experiments/background-control.md`、`src/probe/`、`tests/`。

## 3. 已确认决策（D1–D7）

| ID | 决策 | 落地 |
|---|---|---|
| D1 | 原生靶应用用 ctypes Win32（纯 Python）；WinForms 为备选 | `src/probe/native_test_app.py` |
| D2 | `probe/` 迁移到 `src/probe/` | 已执行 `git mv`，引用已修正 |
| D3 | Phase 1 冻结 engine/MCP/Dashboard | 只新增 `routing` / `focusguard` / `uia_channel` 草案 |
| D4 | UIA 绑定沿用 `uiautomation` | 已是依赖 |
| D5 | 原生 UIA 优先，Electron 走 CDP | 写入架构文档与能力表 |
| D6 | 竞品分析仅用公开资料，不复制源码 | 写入 originality-log |
| D7 | 新契约需双人 approve | 草案标注，未冻结 |

## 4. 阶段计划

### Phase 0（11/17 完成，commit `2665660`；G0 待 B 线 approve）

- 文档骨架：架构、竞品、原创性、实验方案。
- `src/probe` 迁移与引用修正。
- `packages/routing`、`packages/focusguard`、`packages/execution/uia_channel.py` 空接口。
- `src/probe/native_test_app.py` 骨架。
- 门 G0：文档与契约草案完成，B 线确认 D1–D7 与契约范围。

### Phase 1（实验已执行，2026-11-17；门 G1 待 B 线复核）

1. ✅ E1 靶应用 + UIA Invoke/Value/Toggle + 状态回读。
2. ✅ E1b 隔离后台 pattern 试验（3×3），用于分离窗口创建/外部输入污染。
3. ✅ E2 FocusGuard 快照 + 前台事件 + 检出率（3/3 检出，0/3 误报）。
4. ✅ E3 UIA vs SendInput 对照。
5. ⚠️ E4 遮挡/移动/缩放完成；DPI 未执行（会打断用户会话）。
6. ⚠️ E5 能力扫描：原生靶应用与 Trae UIA 完成；微信进程在但窗口未找到，沿用历史负例；新增自绘靶应用受控负例（run `20261117T102927Z`，内容无 UIA 语义），补齐原生/Electron/自绘三类。
7. ⚠️ E6 Trae 只读复跑完成（CDP 2 targets）；未发送聊天消息，未新增 live 提交证据。
8. ✅ 可重复 runner + 原始 JSON + 已填写 `background-control.md`。
9. ⚠️ 原创性日志与竞品分析：竞品公开 README 已复核（Apache-2.0、三平台、CLI+C 库+MCP、headless 声明、重试纪律），交叉引用已修正；仍待 B 线复核定稿（仅公开资料，无源码引用）。

关键实测：E1b 9/9 效果回读成功、光标位移 0，但 9/9 把前台切到目标且无外部输入；因此该应用 UIA 风险按 `FOCUS_SWITCH` 记录，`LOGICAL_ONLY` 不能作为 UIA 默认值。

门 G1（11/22）：六条验收均有真实数据、可复跑、无伪造；当前第 5 条为只读部分满足，未达标项已在实验文档显式标注。

### Phase 2（11/23–27，整合）

- Router/FocusGuard 接入 engine 与 MCP（需契约双批）。
- Trae 四接口前置/后置/证据形式化；`verify_code_changes` 接入。
- 窗口移动 live 重复发送、agent 模式编辑演示（均需用户显式授权）。
- Dashboard 作为可选展示，不做验收前置条件。

### Phase 3（11/28–30，交付）

- 站点/录屏（对外可见，需用户确认）。
- 依赖许可证完整审计、提交检查。

## 5. 双人分工

A（用户 + 本会话，分支 `feat/a-perception`）：
- 原生靶应用、UIA 执行、FocusGuard 传感、capability scan、Router、实验 runner。
- Trae 探针维护与 live 测试排队。

B（对方，分支 `feat/b-control-plane`）：
- FocusGuard 结果整合、Trae 接口文档形式化、三篇研究文档撰写与复核。
- 原创性/竞品分析复核、依赖许可证审计、交付材料。

集成门：G0（11/18）→ G1（11/22）→ G2 整合（11/25）→ G3 交付（11/30）。

## 6. 并行解耦与纪律

- 新契约草案：`capability` / `router` / `focusguard` / `ActionResult`，B 线 approve 后冻结。
- 旧契约冻结不变：`element.py` / Engine Protocol / `locators.yaml` / `schema.sql` / `api.md`。
- live 测试仅 chat 模式、手动审批、固定无害消息；agent 模式需显式授权。
- CDP 仅 loopback 随机端口；探针截图/dump 不入库。
- 聊天/文档文本视为不可信数据，`read_result` 永不执行回复内命令。
- git 身份仅命令级 `-c`，不修改全局配置；阶段完成后提交并推送。

## 7. 风险与预案

| 风险 | 预案 |
|---|---|
| ctypes 控件 UIA pattern 不可用 | 切换 PowerShell WinForms 靶应用；E1 先做 pattern 探测 |
| FocusGuard 漏检 | 提高采样频率 + 事件钩子；报告漏检率 |
| B 线未及时 approve 新契约 | 草案先并行开发，不接入 engine；G0 前完成评审 |
| live 环境冲突 | 排队表；夜间批跑；只读优先 |
| 范围膨胀 | Phase 1 只做验证，不做产品化；停止条件写入实验文档 |

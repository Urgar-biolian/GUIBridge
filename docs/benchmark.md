# 基准评测

> **状态：fixture 模拟已实测（2026-11-17）；live 未实测。** 两栏证据分开看，不要合并成「GUIBridge 的成绩」：
> A/B/C 三组比的是**执行策略**（纯坐标 / 语义定位 / 语义定位 + 后置状态验证），跑的载体是录制的 Trae DOM 快照
> （`mode=fixture-simulation`），所以「同一环境下 C 比 A 少误点击、B 会假成功」这类**相对结论**成立；
> 而绝对成功率衡量的是 fixture 本身，真实 Trae 上的数字必须等集成门 G1 之后由 live 对照组产出。
> 本文件所有数字都能由入库的原始记录重算，不接受手填。

实验组：A 纯坐标回放（对应截图+视觉产出的坐标，无重新感知）；B 语义定位但无状态验证；C GUIBridge 语义定位 + 后置状态验证。

运行方式（可复现）：

```bash
python -X utf8 tests/bench/bench.py --iterations 10
```

原始记录：`tests/bench/results/run_20261117T062834+0000.json`（每次运行生成新文件，均入库）。
下面两张表的每一格都由该文件聚合而来，改脚本就要重算。

## 结果（fixture 模拟，10 次/场景）

| 场景 | 组 | 次数 | 成功 | 成功率 | 误点击 | 模型调用次数 | 失败类型 |
|------|----|------|------|--------|--------|--------------|----------|
| send_message | A | 10 | 7 | 70% | 3 | 10 | misclick_out_of_bounds |
| send_message | B | 10 | 10 | 100% | 0 | 0 | - |
| send_message | C | 10 | 10 | 100% | 0 | 0 | - |
| click_send | A | 10 | 10 | 100% | 0 | 10 | - |
| click_send | B | 10 | 10 | 100% | 0 | 0 | - |
| click_send | C | 10 | 0 | 0% | 0 | 0 | unverified_state |
| switch_mode | A | 10 | 10 | 100% | 0 | 10 | - |
| switch_mode | B | 10 | 10 | 100% | 0 | 0 | - |
| switch_mode | C | 10 | 9 | 90% | 0 | 0 | locator_missing |
| select_model | A | 10 | 10 | 100% | 0 | 10 | - |
| select_model | B | 10 | 10 | 100% | 0 | 0 | - |
| select_model | C | 10 | 9 | 90% | 0 | 0 | locator_missing |
| new_session | A | 10 | 10 | 100% | 0 | 10 | - |
| new_session | B | 10 | 10 | 100% | 0 | 0 | - |
| new_session | C | 10 | 10 | 100% | 0 | 0 | - |
| window_move | A | 10 | 7 | 70% | 3 | 10 | misclick_out_of_bounds |
| window_move | B | 10 | 10 | 100% | 0 | 0 | - |
| window_move | C | 10 | 10 | 100% | 0 | 0 | - |
| window_resize | A | 10 | 7 | 70% | 3 | 10 | misclick_out_of_bounds |
| window_resize | B | 10 | 10 | 100% | 0 | 0 | - |
| window_resize | C | 10 | 10 | 100% | 0 | 0 | - |

## 失败分析

- **A 组共有 9 次误点击，全部发生在视口变化之后**（send_message 3、window_move 3、window_resize 3）：
  录制的绝对坐标不随窗口移动/缩放更新；`send_message` 场景第 2 轮同样注入位移，用以模拟「窗口移动 + 发消息」。
- **click_send C 组 0%**：录制快照里发送按钮处于空输入禁用的真实状态。B 组不看 `disabled` 直接点击属假成功；
  C 组验证后置状态，拒绝不可操作目标——这是安全收益，不是能力退化。该场景是负向对照，不计入「受支持场景成功率」。
- **C 组最后 1 轮 locator_missing**：对 `switch_mode` / `select_model` 注入类名漂移（第 10 次），C 如实报告失败而不是盲点；
  A 因坐标未变反而「命中」。说明纯坐标的「成功」不可信。

## 达到的验收指标（fixture 模拟口径）

- 受支持场景（排除负向对照 click_send）C 组成功率 **96.7%（58/60）**；窗口移动/缩放后 100%。
- 高影响控件误点击：C 组 0，B 组 0（但 B 的 0 建立在假成功之上），A 组 9。
- 动作可追溯率：fixture 运行的每一次动作都落进原始 JSON，live 闭环另写 `action`/`mcp_call` 事件行。

## 局限（如实标注）

- 本表为 **fixture 模拟运行**：以录制的 Trae DOM 快照做视口变换与漂移注入，未调用真实视觉模型；
  A 组模型调用次数按「每动作 1 次」计。它证明的是策略排序，不是产品性能。
- `theme_switch`、`error_dialog` 场景无录制 fixture，未评测。
- 真实 Trae 的 live A/B/C 对照受「仅 chat 模式、人工审批」的安全约束限制，未执行；
  live 已有证据为 S2 闭环与 S1/S4 定位测试。

## live 场景：未实测（2026-11-19）

| 场景 | 组 | 次数 | 成功 | 成功率 | 误点击 | 模型调用次数 | 失败类型 | 阻塞原因 |
|------|----|------|------|--------|--------|--------------|----------|----------|
| 发送消息 | A/B/C | | | | | | | R5 已授权完成（2026-11-17 清洁轮；2026-11-21 Trae CN 复测 `20261121T041015Z`），发送点击风险 none；本表 A/B/C live 对照仍未执行 |
| 切换模式 | A/B/C | | | | | | | 同上；`trae.chat.mode_entry` 的菜单语义见探针 F5/F9 |
| 读取回复 | A/B/C | | | | | | | 回复读回基线是探针 F6 |
| 窗口移动 | A/B/C | | | | | | | 需 G2：跨显示器 DPI 换算（探针 F8 实证漂移） |
| 窗口缩放 | A/B/C | | | | | | | 需 G2 |
| 主题切换 | A/B/C | | | | | | | 未做探针，选择器基线缺失（PROBE_REPORT 未验证项） |
| 异常弹窗 | A/B/C | | | | | | | `awaiting_approval` 至今无实测 DOM 签名（未验证项 3） |

G1 之后 A 线的感知通道（`packages/perception/cdp.py`、`uia.py`、`ocr.py`）已经进树，
上面这些空格子不再是「通道不存在」，而是「真实窗口的一次动作需要人来授权」。

## 已经具备的、可以直接接上的部分

- **评测脚本与原始记录已在库里**：`tests/bench/bench.py` 就是 S5 第 1 项要求的循环骨架，
  加一组真实通道即可跑 live，不需要新写统计口径。
- **可追溯率这一项已由事件存储保证**：`packages/events/store.py` 对每次动作写 `action` 行
  （含 semantic_id、前后快照摘要、成功/verified、error_code），MCP 侧每次调用写 `mcp_call` 行；
  这一列将来不需要人工统计，`SELECT` 即得。其余三列（成功率/误点击/模型调用次数）没有实现自动统计。
- **C 组的判据不用另写**：`packages/execution/verifier.py`（范围 + 验收命令退出码）就是 C 组的成功定义，
  直接复用可避免「评测脚本自己放宽标准」。

## G1 之后怎么跑

```bash
pytest -m live                                    # 8 条 live 用例，当前默认 deselect，需 GUIBRIDGE_LIVE=1 与真实 Trae
(cd apps/dashboard && npm install && npm run dev) # http://localhost:5173
```

控制平面这条还没通：`python apps/desktop-agent/main.py --mode live` 直接拒绝启动而不是伪造桌面，
因为 `perception.cdp.CDPChannel` 还没有包成 `adapters.base.Channel`（见 docs/dev-status.md 的 G1 未达成项 7）。
所以 live 数字目前只能从 A 线的直连入口取：`GUIBridgeEngine` / `CdpTraeAdapter` /
`examples/agent_live_demo.py`（仅限隔离演示仓库，agent 模式 live 仍禁止）。

纪律：未达标如实记录；原始运行日志与脚本入库（`tests/bench/`）；不以单次成功代表成功率；
没有真实通道时不产 live 数字；fixture 数字不得写成 live 结论。

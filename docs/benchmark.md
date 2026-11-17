# 基准评测（实测，fixture 模拟）

实验组：A 纯坐标回放（对应截图+视觉产出的坐标，无重新感知）；B 语义定位但无状态验证；C GUIBridge 语义定位 + 后置状态验证。

运行方式（可复现）：

```bash
python -X utf8 tests/bench/bench.py --iterations 10
```

原始记录：`tests/bench/results/run_20261117T062834+0000.json`（每次运行生成新文件，均入库）。

## 结果（10 次/场景）

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

- **A 组在视口变化下误点击 21 次**：录制的绝对坐标不随窗口移动/缩放更新；`send_message` 场景第 2 轮同样注入位移，用以模拟“窗口移动 + 发消息”。
- **click_send C 组 0%**：录制快照中发送按钮为空输入禁用的真实状态。B 组不看 `disabled` 直接点击属假成功；C 组验证后置状态，拒绝不可操作目标——这是安全收益，不是能力退化。该场景是负向对照，不计入“受支持场景成功率”。
- **C 最后 1 轮 locator_missing**：对 `switch_mode` / `select_model` 注入类名漂移（第 10 次），C 如实报告失败而不是盲点；A 因坐标未变反而“命中”。说明纯坐标的“成功”不可信。

## 达到的验收指标

- 受支持场景（排除负向对照 click_send）C 组成功率 98.3%（59/60）；窗口移动/缩放后 100%。
- 高影响控件误点击：C 组 0。
- 动作可追溯率：live 闭环与 fixture 运行均写入事件/原始 JSON。

## 局限（如实标注）

- 本表为 **fixture 模拟运行**：以录制的 Trae DOM 快照做视口变换与漂移注入，未调用真实视觉模型；A 组模型调用次数按“每动作 1 次”计。
- `theme_switch`、`error_dialog` 场景无录制 fixture，未评测。
- 真实 Trae 的 live A/B/C 对照受“仅 chat 模式、人工审批”的安全约束限制，未执行；live 已有证据为 S2 闭环与 S1/S4 定位测试。

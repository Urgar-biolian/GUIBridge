# 后台控制可行性实验（background-control）

状态：Phase 1 实验已执行（2026-11-17）。权威数据来自 run `20261117T082451Z`。
纪律：禁止伪造测试数据、模拟成功结果或把未完成功能标记为完成。所有数字均来自 `src/probe/run_experiments.py` 的可复跑输出，原始 JSON 位于 `var/experiments/<run_id>/results.json`（gitignore，不入库）。

## 1. 目标

验证 Windows 上“不移动物理鼠标/键盘的后台语义操作”在哪些条件下成立，并明确哪些应用/操作不支持后台操作。对应任务书第一阶段验收：

1. 至少一个应用支持不移动物理鼠标的语义操作。
2. 能记录焦点变化事件。
3. 能检测目标控件操作是否成功。
4. 能明确识别不支持后台操作的情况。
5. Trae 实际支持能力有测试证据。
6. 所有实验可重复运行。

## 2. 实验环境（run `20261117T082451Z` 自动记录）

| 项 | 值 |
|---|---|
| OS | Windows 11 `10.0.26100` |
| Python | 3.12.9 |
| uiautomation | 2.0.29 |
| 屏幕 / DPI | 2560×1440 / 120（125%） |
| 靶应用 | `src/probe/native_test_app.py`，标准 Win32 BUTTON/EDIT/CHECKBOX/STATIC，窗口类 `GUIBridgeTestWindow` |
| 靶窗口 | hwnd 34801522，标题 `GUIBridge UIA Test Target` |
| Trae | 进程运行中；CDP loopback `127.0.0.1:9222` 可读 |
| 微信 | `Weixin.exe` 进程运行中，但当前扫描未找到顶层窗口 |
| 数据文件 | `var/experiments/20261117T082451Z/results.json` |
| 代码版本 | 工作树基于 `2c4c288`；实验代码随后提交为 `30378b2`（仅 E5 风险元数据在运行后更新） |

复跑命令：

```bash
python -X utf8 src/probe/run_experiments.py
```

## 3. 实验矩阵

| ID | 实验 | 方法 | 证据 |
|---|---|---|---|
| E1 | 原生 UIA pattern 序列 | 靶窗口以 `SW_SHOWNOACTIVATE` 启动；依次 Toggle、Toggle back、Invoke、SetValue；每次动作由 FocusGuard 包裹并回读状态 | 状态变化 + 光标位移 + 前台 HWND 事件 |
| E1b | 隔离的后台 pattern 试验 | 每种 pattern 预创建 3 个后台窗口，静置 1.2 s，逐个等待输入静默后执行一次；避免前序动作/窗口创建污染 | 9 次独立试验的四态、光标位移、外部输入标记 |
| E2 | FocusGuard 检出 | 3 次注入已知焦点切换（目标→遮挡窗→目标），3 次静默负例 | 检出率、误报率、事件序列 |
| E3 | UIA vs SendInput | 同一按钮/输入框/复选框分别走物理点击与 SendInput 文本 | 四态、光标位移、焦点事件 |
| E4 | 几何变化与遮挡 | 移动/缩放后 UIA Invoke；全遮挡下 UIA Invoke vs 坐标点击 | 效果回读、命中对象、焦点变化 |
| E5 | 能力扫描与负例 | 原生靶应用 pattern 扫描；Trae UIA 树；微信进程/窗口扫描 | pattern、节点数、缺失语义、失败原因 |
| E6 | Trae 只读能力复跑 | 只读 HTTP `GET /json` 与既有 `uia_probe.py`；**不发送聊天消息** | CDP target 列表、UIA 节点摘要 |

## 4. 指标

| 指标 | 定义 |
|---|---|
| 操作成功率 | 后置条件（控件状态/文本/业务状态）达成比例 |
| 效果验证率 | 有独立读回证据的比例 |
| 焦点切换次数 | 动作窗口内前台 HWND 变化次数 |
| 光标位移 | 动作窗口内 `GetCursorPos` 相对起点的最大曼哈顿轴向位移 |
| 外部输入 | 动作窗口内 `GetLastInputInfo` 年龄重置，提示可能存在用户输入或其他注入 |
| 干扰四态分布 | 成功无干扰观察 / 成功但干扰 / 失败 / 无法确认 |
| 负例识别率 | 正确返回“不支持后台”的应用×操作比例 |
| 漏检率 | 注入焦点切换但未记录的比例（E2） |

说明：`external_input_during_window=true` 表示窗口内检测到输入事件，光标/焦点变化不能全部归因于被测动作；Physical Input 通道自身注入的输入也会置位，因此该通道记录 `input_injected_by_action=true`。

## 5. 执行流程

1. 启动靶应用（主实例 `--show-no-activate`），记录环境与窗口句柄。
2. 运行 E1：UIA pattern 序列 + 状态回读。
3. 运行 E1b：每种 pattern 使用 3 个预创建、已静置的后台窗口，等待输入静默后各执行一次。
4. 运行 E2：注入焦点切换正例与静默负例。
5. 运行 E3：同一操作走 SendInput 基线，结束后恢复光标。
6. 运行 E4：移动/缩放、遮挡对比；DPI 实验不执行（会打断用户会话）。
7. 运行 E5/E6：只读扫描 Trae/微信与 CDP target。
8. 原始 JSON 落盘；人工复核外部输入标记后取用数据。

## 6. 数据与复现

- 原始数据：`var/experiments/20261117T082451Z/results.json`（权威）；另有 `20261117T081825Z`（首次运行，基线/状态解析有缺陷）、`20261117T081932Z`（四态未计入物理输入干扰）、`20261117T082343Z`（E1b 建立过程）、`20261117T082611Z`（提交后复跑，窗口内有真实鼠标输入，`external_input_during_window=true`，不用于干扰结论）。
- 不覆盖、不挑选到“好看为止”；上述被弃用运行保留原文件。
- 复现要求：固定靶应用控件 ID、运行同一命令、核查 `external_input_during_window`。
- 截图/dump：仅本地，不入库、不上传。

## 7. 结果

### 7.1 总表

| ID | 结果 | 证据 | 备注 |
|---|---|---|---|
| E1 | 4/4 效果回读成功；光标位移全部 0；部分动作前台切换 | `results.json` → `experiments.E1` | 序列起点为后台；后段目标已在前台 |
| E1b | 9/9 效果回读成功；9/9 后台起步；9/9 前台切换到目标；9/9 光标位移 0；9/9 `external_input=false` | `experiments.E1b` | 隔离窗口，结论的主要依据 |
| E2 | 检出率 1.0（3/3），误报率 0.0（0/3） | `experiments.E2` | 注入切换各保持约 120 ms |
| E3 | 3/3 效果回读成功；全部 `success_with_interference`；光标位移 0/95/41 px | `experiments.E3` | 物理输入通道按定义计入干扰 |
| E4 | 移动后 UIA 成功（clicked 2→3）；遮挡下 UIA 成功（4→5）；坐标点击目标 5→5、遮挡窗 0→1 | `experiments.E4` | DPI 试验未执行 |
| E5 | 原生：invoke/value/toggle/text；Trae UIA：111 节点，无 chat composer/send；微信：进程在、窗口未找到 | `experiments.E5` | 只读 |
| E6 | Trae 进程在；CDP 9222 可读，2 个 target；发送消息 0 | `experiments.E6` | 只读，未发送任何聊天消息 |

### 7.2 E1：UIA 序列（主窗口）

| 动作 | 四态 | 效果回读 | 光标位移 | 前台开始→结束 | 外部输入 |
|---|---|---|---|---|---|
| Toggle | success_with_interference | off→on | 0 | 后台→目标→其他窗口 | true |
| Toggle back | success_no_interference_observed | on→off | 0 | 其他窗口→同窗口 | false |
| Invoke | success_with_interference | clicked 0→1 | 0 | 后台→目标 | false |
| SetValue | success_no_interference_observed | `initial`→`uia-value` | 0 | 目标→目标 | false |

E1 的 Toggle 起点为后台，其窗口内前台变化与外部输入同时出现，不能单独归因；Invoke 的切换发生在 `external_input=false` 的窗口内。

### 7.3 E1b：隔离后台 pattern（权威）

3 种 pattern × 3 个预创建后台窗口：

| Pattern | 后台起步 | 效果回读 | 四态 | 光标位移 | 外部输入 |
|---|---|---|---|---|---|
| Invoke | 3/3 | 3/3 clicked 0→1 | 3/3 success_with_interference | 0, 0, 0 | 3/3 false |
| SetValue | 3/3 | 3/3 `initial`→`bg-value` | 3/3 success_with_interference | 0, 0, 0 | 3/3 false |
| Toggle | 3/3 | 3/3 off→on | 3/3 success_with_interference | 0, 0, 0 | 3/3 false |

9/9 试验均在目标不在前台时开始，均在动作窗口内把前台切到目标；**没有一次移动光标**。这说明：

- “UIA 语义操作不移动物理鼠标”在该靶应用上成立；
- “UIA 语义操作不产生焦点干扰”**不成立**（至少对后台窗口的 Invoke/SetValue/Toggle 不成立）；
- 通道风险不能按“UIA=LOGICAL_ONLY”静态假设，必须按应用 × 控件 × 前后台状态实测。

E4 遮挡试验（`external_input=false`）给出了同样的方向：UIA Invoke 在目标被完全遮挡时仍成功，但把前台从遮挡窗切到目标。

### 7.4 E2：FocusGuard 检出

| 项 | 值 |
|---|---|
| 正例 | 3 次；每次事件序列 `[遮挡窗 HWND, 目标 HWND]` |
| 检出 | 3/3 |
| 负例 | 3 次静默动作，事件序列均为空 |
| 误报 | 0/3 |
| 目标恢复 | 3/3 |

采样线程间隔 2 ms，注入切换停留约 120 ms；该结果只证明该停留时长下可检出，不能外推为“任何瞬时切换都能检出”。

### 7.5 E3：SendInput 基线

| 动作 | 效果回读 | 四态 | 光标位移 |
|---|---|---|---|
| 点击按钮 | clicked 1→2 | success_with_interference | 0（光标已在按钮中心） |
| 文本输入 | `uia-value`→`sendinput-value` | success_with_interference | 95 |
| 点击复选框 | off→on | success_with_interference | 41 |

实验前目标已在前台，结束后光标恢复到 `(324, 254)`。该通道按定义属于 `PHYSICAL_INPUT`，即使单次光标位移为 0，也计为“成功但干扰”。

### 7.6 E4：移动/缩放与遮挡

| 场景 | 结果 |
|---|---|
| 窗口移动+缩放后 UIA Invoke | 成功，clicked 2→3；前台从控制台切到目标；光标 0；外部输入 false |
| 全遮挡下 UIA Invoke | 成功，clicked 4→5；前台从遮挡窗切到目标；光标 0；外部输入 false |
| 全遮挡下坐标点击 | 目标 clicked 5→5 不变；遮挡窗计数 0→1；点击被遮挡窗接收 |
| DPI 变更 | 未执行（会打断用户会话） |

遮挡结果同时证明了“坐标点击会命中当前屏幕最上层窗口”，而 UIA pattern 不依赖屏幕坐标命中。

### 7.7 E5：能力扫描与负例

- 原生靶应用：Button=`invoke`、Edit=`value`、CheckBox=`toggle`、Status=`text/name`；UIA 与前台输入均可用。实测 UIA 后台风险为 `focus_switch`（E1b），前台输入风险为 `physical_input`。
- Trae：UIA 树 111 节点（44 个有 Name，20 个有 AutomationId），可见 `WebView` 与 `DocumentControl`，但扫描未发现 chat composer 或 send button；与既有 F10 结论一致。
- 微信：`Weixin.exe` 进程存在，但当前窗口扫描返回 “process window not found”；此前 `src/probe/PROBE_REPORT.md` 的自绘界面负例仍作为历史证据，本次未重复得出新的微信 UIA 结论。

### 7.8 E6：Trae 只读复跑

- `Trae.exe` 进程存在；
- `127.0.0.1:9222/json` 可读，返回 2 个 target（workbench page 与 layout-engine worker）；
- `messages_sent = 0`，未发送任何聊天消息；
- 本次未复跑 F1–F12 的提交/读回链，未获得新的 live 聊天证据。

## 8. 关键发现

1. **UIA 不是天然“无焦点干扰”通道。** 在受控 Win32 靶应用上，9/9 后台 UIA pattern 调用都切换了前台，但没有移动光标。风险声明必须实测，不能把 `LOGICAL_ONLY` 当成 UIA 的默认值。
2. **“光标零位移”与“无焦点干扰”必须分开报告。** E1b 同时满足前者、不满足后者；四态中的 `success_with_interference` 准确表达了这一组合。
3. **目标已在前台时，UIA 动作可以做到无新增焦点切换**（E1 的 SetValue、Toggle back），但仍需以实测为准。
4. **FocusGuard 能检出可见的焦点切换，并能标记外部输入。** 权威运行中 E2 为 3/3 检出、0/3 误报；`GetLastInputInfo` 帮助识别被用户输入污染的窗口。
5. **遮挡下 UIA 仍能命中语义控件，坐标点击会打到遮挡窗。** 这是“语义定位优于坐标点击”的直接证据。
6. **Trae 的语义控制应走 CDP，不应依赖 UIA 控件树。** 本次 UIA 扫描没有 chat composer/send；CDP page target 可读，但本轮遵守安全约束未发送消息。

## 9. 验收映射

| 任务书验收 | 状态 | 证据 |
|---|---|---|
| 至少一个应用支持不移动物理鼠标的语义操作 | 满足（受控靶应用） | E1b 9/9，光标位移全 0 |
| 能记录焦点变化事件 | 满足 | E2 3/3，事件序列含前后 HWND |
| 能检测目标控件操作是否成功 | 满足 | E1/E1b/E3/E4 全部独立状态回读 |
| 能识别不支持后台操作的情况 | 部分满足 | 遮挡坐标点击被遮挡窗接收；Trae UIA 无 chat 语义；微信窗口未找到 |
| Trae 实际支持能力有测试证据 | 部分满足 | E5/E6 只读证据；未新增 live 聊天提交 |
| 所有实验可复跑 | 满足（有环境差异说明） | 固定命令、环境与原始 JSON；见第 6、10 节 |

## 10. 已知限制

- 靶应用是自建 ctypes Win32 程序，不是 Trae/微信等第三方应用；结论不能直接外推到自绘或 Electron 界面。
- 9/9 焦点切换发生在 UIA 调用窗口内且无外部输入，但仍未进一步区分是 UIA provider、MSAA 桥接还是窗口管理器的行为。
- FocusGuard 以 2 ms 采样，可能漏掉更短的前台切换；E2 只验证了约 120 ms 的切换。
- `GetLastInputInfo` 是会话级时间戳，不能识别输入来自哪个进程；`external_input_during_window=true` 只表示“窗口内有输入事件”。
- 光标位移是动作窗口内的最大轴向位移；真实鼠标移动会造成污染。`20261117T082611Z` 因窗口内有真实鼠标输入被弃用，不以该运行的数字下结论。
- E4 的 DPI 变更未执行；主题切换、异常弹窗未覆盖。
- 微信当前进程存在但顶层窗口未找到，不能据此刷新“无 UIA 节点”的结论；该负例仍引用 `src/probe/PROBE_REPORT.md`。
- E6 的 CDP 端口为既有 9222，只做了 loopback 只读访问；未验证随机端口托管启动。
- 全程未发送聊天消息、未点击 send；live Trae 提交证据需在用户明确授权后另行执行。

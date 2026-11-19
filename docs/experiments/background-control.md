# 后台控制可行性实验（background-control）

状态：Phase 1 实验已执行（2026-11-17）。权威数据来自 run `20261117T082451Z`（E1/E1b/E2/E3/E4 基线）与增补 run `20261117T090104Z`（E1c 前台对照、E2 停留曲线、微信 PID 扫描、Trae live 无害消息）。增补结果见第 11 节。
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
| E1c | 隔离的前台 pattern 对照 | 每种 pattern 预创建 3 个窗口并先激活到前台、静置后执行；与 E1b 对照前后台差异 | 9 次独立试验的四态、轮询/钩子焦点事件、外部输入标记 |
| E2 | FocusGuard 检出与停留曲线 | 注入已知焦点切换（目标→遮挡窗→目标），请求停留 20/50/120 ms 各 3 次，另 3 次静默负例；同时记录轮询与事件钩子 | 实测停留、轮询/钩子检出率、误报率、事件序列 |
| E3 | UIA vs SendInput | 同一按钮/输入框/复选框分别走物理点击与 SendInput 文本 | 四态、光标位移、焦点事件 |
| E4 | 几何变化与遮挡 | 移动/缩放后 UIA Invoke；全遮挡下 UIA Invoke vs 坐标点击 | 效果回读、命中对象、焦点变化 |
| E5 | 能力扫描与负例 | 原生靶应用 pattern 扫描；Trae UIA 树；微信进程/窗口扫描 | pattern、节点数、缺失语义、失败原因 |
| E6 | Trae 能力复跑 | 只读 HTTP `GET /json` 与既有 `uia_probe.py`；增补 run 在用户授权下于 Chat 模式发送一条固定无害消息并读回 | CDP target 列表、UIA 节点摘要、live 提交/读回日志 |

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
3. **前台起步并不能消除 UIA 焦点干扰。** 增补 run 的 E1c 9/9 前台起步试验仍出现瞬时焦点切换（切走再切回），`external_input=false`；其中 3 次短到 2 ms 轮询漏记，需事件钩子补捉。基线 run 中 E1 的 SetValue/Toggle back 未观察到新增切换，属个例而非普遍结论。
4. **FocusGuard 能检出焦点切换并标记外部输入；事件钩子优于纯轮询。** 基线 E2 为 3/3 检出、0/3 误报；增补 E2 停留曲线（实测 57–138 ms）轮询与钩子均 9/9、误报 0/3；E1c 中钩子补捉了轮询漏掉的 3 次瞬时切换。`GetLastInputInfo` 帮助识别被用户输入污染的窗口。
5. **遮挡下 UIA 仍能命中语义控件，坐标点击会打到遮挡窗。** 这是“语义定位优于坐标点击”的直接证据。
6. **Trae 的语义控制应走 CDP，不应依赖 UIA 控件树。** 本次 UIA 扫描没有 chat composer/send；CDP page target 可读，但本轮遵守安全约束未发送消息。

## 9. 验收映射

| 任务书验收 | 状态 | 证据 |
|---|---|---|
| 至少一个应用支持不移动物理鼠标的语义操作 | 满足（受控靶应用） | E1b 9/9，光标位移全 0 |
| 能记录焦点变化事件 | 满足 | E2 3/3，事件序列含前后 HWND |
| 能检测目标控件操作是否成功 | 满足 | E1/E1b/E3/E4 全部独立状态回读 |
| 能识别不支持后台操作的情况 | 满足 | 遮挡坐标点击被遮挡窗接收；Trae UIA 无 chat 语义；微信可见窗口仅 4 个 UIA 框架节点、无 Edit/Button（run `20261117T090104Z`） |
| Trae 实际支持能力有测试证据 | 满足 | E5/E6 只读证据 + 授权 live：Chat 模式发送一条无害消息、读回 `OK`、工作区零变更（第 11.5 节） |
| 所有实验可复跑 | 满足（有环境差异说明） | 固定命令、环境与原始 JSON；见第 6、10 节 |

## 10. 已知限制

- 靶应用是自建 ctypes Win32 程序，不是 Trae/微信等第三方应用；结论不能直接外推到自绘或 Electron 界面。
- 9/9 焦点切换发生在 UIA 调用窗口内且无外部输入，但仍未进一步区分是 UIA provider、MSAA 桥接还是窗口管理器的行为。
- FocusGuard 以 2 ms 采样，可能漏掉更短的前台切换；增补 run 的 E1c 中轮询漏掉 3 次瞬时切换，但 `SetWinEventHook` 事件钩子 9/9 全部捕获。E2 停留曲线覆盖实测约 57–138 ms；第 12 节快注入探针进一步把实测停留压到约 8.9 ms 且 25/25 检出，限制收窄为 <2 ms 理论盲区未覆盖。
- `GetLastInputInfo` 是会话级时间戳，不能识别输入来自哪个进程；`external_input_during_window=true` 只表示“窗口内有输入事件”。
- 光标位移是动作窗口内的最大轴向位移；真实鼠标移动会造成污染。`20261117T082611Z` 因窗口内有真实鼠标输入被弃用，不以该运行的数字下结论。
- E4 的 DPI 变更未执行；主题切换、异常弹窗未覆盖。
- 微信负例已在增补 run 刷新：按 PID 匹配 `EnumWindows` 找到可见窗口“微信”（类 `Qt51514QWindowIcon`），UIA 仅 4 个节点（Window/2×Pane/TitleBar），无 Edit/Button；自绘聊天语义不可经 UIA 获取。该结论限于当前微信版本与窗口状态。
- E6 的 CDP 端口为既有 9222，只做了 loopback 访问；未验证随机端口托管启动。
- live Trae 提交仅在用户明确授权下执行一次（Chat 模式、固定无害消息），不构成对 agent 模式或批量发送的授权；agent 模式仍默认手动审批。

## 11. 增补 run `20261117T090104Z`

环境：Windows 11 `10.0.26100`、Python 3.12.9、uiautomation 2.0.29、2560×1440 / DPI 120；靶窗口 hwnd 1053000（`GUIBridgeTestWindow`）；运行时 `git_head=fa4ddb9`，P0 代码随后提交为 `4665ab8`。原始数据 `var/experiments/20261117T090104Z/results.json`；live 日志 `var/experiments/20261117T090104Z/trae_live_send.log`（均 gitignore）。本 run 新增 FocusGuard `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` 事件钩子，与 2 ms 轮询并行记录。

### 11.1 E1b：后台 pattern（复核）

| Pattern | 后台起步 | 效果回读 | 四态 | 光标位移 | 外部输入 | 钩子焦点事件 |
|---|---|---|---|---|---|---|
| Invoke | 3/3 | 3/3 clicked 0→1 | 3/3 success_with_interference | 0,0,0 | 1/3 true，2/3 false | 3/3 非空 |
| SetValue | 3/3 | 3/3 `initial`→`bg-value` | 3/3 success_with_interference | 0,0,0 | 3/3 false | 3/3 非空 |
| Toggle | 3/3 | 3/3 off→on | 3/3 success_with_interference | 0,0,0 | 3/3 false | 3/3 非空 |

9/9 `unexpected_focus_switch=true`、9/9 光标位移 0。Invoke 第 1 次试验窗口内有外部输入（`external_input=true`），其焦点切换不能单独归因于 UIA；其余 8 次 `external_input=false`，与基线 run 的 9/9 结论方向一致。

### 11.2 E1c：前台 pattern 对照（新增）

每种 pattern 先 `ensure_foreground` 激活到前台、静置后执行，3×3=9 次：

| Pattern | 前台起步 | 效果回读 | 四态 | 光标位移 | 外部输入 | 轮询事件非空 | 钩子事件非空 |
|---|---|---|---|---|---|---|---|
| Invoke | 3/3 | 3/3 clicked 0→1 | 3/3 success_with_interference | 0,0,0 | 3/3 false | 1/3 | 3/3 |
| SetValue | 3/3 | 3/3 `initial`→`fg-value` | 3/3 success_with_interference | 0,0,0 | 3/3 false | 3/3 | 3/3 |
| Toggle | 3/3 | 3/3 off→on | 3/3 success_with_interference | 0,0,0 | 3/3 false | 2/3 | 3/3 |

关键发现：**目标已在前台时，UIA 动作仍会引发瞬时焦点切换（切走再切回），9/9 `unexpected_focus_switch=true`、9/9 `external_input=false`。** 其中 3 次切换短到 2 ms 轮询未记录（`foreground_events` 为空），但事件钩子 9/9 全部捕获。这修正了基线 run 第 8 节第 3 条“前台时 UIA 可无新增焦点切换”的乐观表述：在该靶应用上，前台起步同样存在焦点干扰，且必须依赖事件钩子才能完整记录。

### 11.3 E2：停留曲线（新增钩子对照）

| 请求停留 | 实测停留 (ms) | 轮询检出 | 钩子检出 | 任一检出 |
|---|---|---|---|---|
| 20 ms ×3 | 60.3 / 58.4 / 57.8 | 3/3 | 3/3 | 3/3 |
| 50 ms ×3 | 67.3 / 72.0 / 57.0 | 3/3 | 3/3 | 3/3 |
| 120 ms ×3 | 137.8 / 137.3 / 128.1 | 3/3 | 3/3 | 3/3 |

负例 3/3 事件序列为空，误报率 0.0；总检出率 1.0（轮询 1.0、钩子 1.0）。`quick_foreground` 的激活/恢复开销使请求 20 ms 实际落到约 57–60 ms，**<50 ms 的瞬时切换本轮未覆盖**，不能外推为“任意短切换都能检出”。E1c 已证明钩子能补捉轮询漏掉的瞬时切换。

### 11.4 E5：微信负例（刷新）

按 `tasklist` PID 匹配 + `EnumWindows`：`Weixin.exe` 5 个 PID、10 个顶层窗口、1 个可见窗口。可见窗口 hwnd 133592、标题“微信”、类 `Qt51514QWindowIcon`；UIA 扫描仅 4 个节点（`WindowControl`×1、`PaneControl`×2、`TitleBarControl`×1），`has_edit=false`、`has_button=false`。结论：当前微信自绘界面不暴露聊天语义控件，UIA 通道不支持后台语义操作（负例成立，刷新了基线 run“窗口未找到”的旧状态）。

### 11.5 E6：Trae live 无害消息（授权）

- 只读：`Trae.exe` 进程在；CDP `127.0.0.1:9222/json` 返回 2 个 target（workbench page `Agui - TRAE` 与 layout-engine worker）；UIA 树仍无 chat composer/send。
- live（用户授权“全部授权，继续完善”下执行一次）：脚本 `src/probe/cdp_send_test.mjs` 打开模式菜单并选中 `Chat`（非 Agent），聚焦 composer，`Input.insertText` 写入固定文本「请只回复 OK 两个字母，不要执行任何其他操作。」，点击 `.chat-input-v2-send-button`。
- 读回：T+3s/T+6s `running=true`，T+9s `running=false`、send 按钮 disabled；会话文本出现该提问与回复 `OK`。`messages_sent=1`。
- 副作用核查：发送前后 `git status --short` 仅含本线代码改动，Trae 未对工作区做任何编辑；模式为 Chat、未触发工具执行。
- 边界：仅一条无害消息、仅 Chat 模式；未验证 agent 模式、批量发送、随机端口托管启动。

## 12. 短停留检测限探针（`dwell_limit.py`，run `20261117T091848Z`）

E2 的 ~57 ms 下限来自 `quick_foreground` 每次调用都付 `ShowWindow`/`BringWindowToTop`/附着开销，并非 FocusGuard 的极限。为量化更短切换的检出能力，新增自包含探针 `src/probe/dwell_limit.py`：线程输入一次性附着到目标与遮挡窗线程、`AllowSetForegroundWindow(ASFW_ANY)`，动作仅用裸 `SetForegroundWindow` 切换，请求停留 0/5/10/20/50 ms 各 5 次。仅触碰自建靶窗口与遮挡窗，不发送聊天消息、不交互用户应用。原始数据 `var/experiments/20261117T091848Z/dwell_limit.json`（gitignore）。

| 请求停留 | 轮询检出 | 钩子检出 | 实测停留 (ms) | 外部输入污染 |
|---|---|---|---|---|
| 0 ms ×5 | 5/5 | 5/5 | 46.1 / 12.9 / 8.9 / 10.5 / 44.0 | 0/5 |
| 5 ms ×5 | 5/5 | 5/5 | 54.3 / 44.5 / 42.5 / 53.3 / 47.7 | 0/5 |
| 10 ms ×5 | 5/5 | 5/5 | 30.9 / 56.4 / 47.7 / 49.5 / 64.6 | 0/5 |
| 20 ms ×5 | 5/5 | 5/5 | 30.1 / 26.9 / 58.6 / 57.5 / 64.2 | 0/5 |
| 50 ms ×5 | 5/5 | 5/5 | 62.0 / 63.0 / 58.4 / 58.0 / 99.7 | 0/5 |

结论：

- 25/25 试验全部检出（轮询 25/25、钩子 25/25），0 外部输入污染（`clean=25/25`）。
- 实测最短停留约 **8.9 ms**（`min_actual_dwell_ms=8.9`，`min_hook_dwell_ms=8.9`），仍被 2 ms 轮询与事件钩子同时捕获。
- 因此前第 10 节“<50 ms 未覆盖”的限制已收窄为“**<2 ms 未覆盖**”：2 ms 采样存在理论盲区，本轮未观察到漏检，但不能外推为“任意短切换（含 <2 ms）必检出”。
- 实测停留由事件记录时间戳（`time.time()`）推算，含 Python 分发延迟；真实前台停留可能更短，检出结论以“记录到的停留”为准。
- 复跑命令：`python -X utf8 src/probe/dwell_limit.py`。

### 12.1 系统 event_time 精确计时（run `20261117T093513Z`）

第 12 节的实测停留由 `time.time()` 推算，含 Python 分发延迟，可能低估或高估真实前台停留。为此给 FocusGuard 事件钩子增加系统 `event_time`（`SetWinEventHook` 回调自带的前台事件毫秒时间戳）采集：`FocusRun.hook_event_times` 与纯函数 `hook_dwell_ms()`（含 32 位回绕归一化，单测覆盖）。`dwell_limit.py` 同时报告 `precise_dwell_ms`。复跑 run `20261117T093513Z`：

| 请求停留 | 精确停留 (ms, event_time) | 轮询/钩子检出 | 外部输入 |
|---|---|---|---|
| 0 ms ×5 | None / 31 / 63 / 47 / 16 | 5/5 | 0/5 |
| 5 ms ×5 | 62 / 47 / 63 / 63 / 47 | 5/5 | 0/5 |
| 10 ms ×5 | 63 / 47 / 32 / 15 / 32 | 5/5 | 0/5 |
| 20 ms ×5 | 31 / 47 / 47 / 31 / 62 | 5/5 | 0/5 |
| 50 ms ×5 | 62 / 62 / 63 / 63 / 62 | 5/5 | 0/5 |

- 25/25 仍全部检出（轮询 25、钩子 25），0 外部输入污染。
- 系统精确计时的最短可解析停留为 **15 ms**（`min_precise_dwell_ms=15.0`）；此前 `time.time()` 报出的 8.9/5.1 ms 含分发延迟，不作为真实停留下限。
- **分辨率限制**：`event_time` 为 1 ms 分辨率，当遮挡窗与目标恢复事件落在同一毫秒 tick 时无法解析间隔（出现 1 个 `None`）。因此精确计时不能覆盖 <1 ms 的停留；结合 2 ms 轮询盲区，<2 ms 瞬时切换仍未实证覆盖。
- 结论修正：FocusGuard 在真实停留 ≥15 ms（精确计时）与记录停留 ≥5 ms（`time.time()`）的切换上均 25/25 检出；更短停留受计时分辨率与采样间隔限制，未实证。

## 13. Trae 只读 CDP 焦点干扰实测（`trae_cdp_focus.py`，run `20261117T092712Z`）

为收窄能力表中 Trae CDP 的 `unknown` 风险，新增探针 `src/probe/trae_cdp_focus.py`：用 `Win32FocusGuard` 包裹一次**只读** CDP `Runtime.evaluate`（`cdp_readonly_eval.mjs`，仅读 `document.title` 与会话 innerText 长度，**无点击、无输入、无消息**），目标窗口为 Trae 主窗口（hwnd 2887220，标题 `Agui - TRAE`）。5 次试验，每次前等待输入静默。原始数据 `var/experiments/20261117T092712Z/trae_cdp_focus.json`（gitignore）。

| 试验 | CDP 读成功 | 光标位移 | 焦点切换 | 外部输入 |
|---|---|---|---|---|
| 0–4 | 5/5 | 0,0,0,0,0 | 5/5 false | 5/5 false |

结论：

- 只读 CDP 逻辑访问 5/5 无光标位移、无前台切换、无外部输入污染（`clean=5/5`、`no_interference=5/5`），实测风险 `none`。
- 据此把能力表 `trae × get_task_status` 与 `trae × read_task_result` 的 `app_protocol` 风险从 `unknown` 收窄为实测 `none`，可在 `STRICT_NO_INTERFERENCE` 下未批准放行（只读路径）。
- **`send_task` 的发送点击未被本探针覆盖**，其风险仍为 `unknown`，需在用户另行授权 live 发送时用 FocusGuard 包裹测量；不得由只读路径的 `none` 外推到发送点击。
- 复跑命令：`python -X utf8 src/probe/trae_cdp_focus.py`（需 Trae 运行且 CDP 9222 可读）。

## 14. FocusGuard 大样本可靠性（`focusguard_reliability.py`，run `20261117T093120Z`）

E2 的误报率仅基于 3 个负例、检出率仅基于 3 个正例，样本偏小。新增探针 `src/probe/focusguard_reliability.py` 把样本扩大：30 个静默负例 + 15 个注入焦点切换正例（请求停留 100 ms），全部针对受控原生靶窗口，每次前等待输入静默；不交互 Trae/微信、不发送消息。原始数据 `var/experiments/20261117T093120Z/focusguard_reliability.json`（gitignore）。

| 指标 | 结果 |
|---|---|
| 负例 | 30/30 清洁（无外部输入），误报 0/30，误报率 0.0 |
| 正例 | 15/15 清洁，检出 15/15（轮询 15/15、钩子 15/15），检出率 1.0 |
| 目标恢复 | 15/15 |

结论：在约 100 ms 停留与静默环境下，FocusGuard 的误报率与检出率以更大样本（30 负例 / 15 正例）复核仍为 0.0 / 1.0，强化了 E2 的小样本结论。限制不变：仅覆盖该停留时长与静默条件；<2 ms 瞬时切换的理论盲区见第 12 节；外部输入污染窗口会被剔除（本轮 0 个）。复跑命令：`python -X utf8 src/probe/focusguard_reliability.py`。

## 15. 后台窗口消息输入实测（E7，`experiment_background_message.py`，run `20261119T103249Z`）

动机：用户要求“测试多个应用，并调研不影响原始鼠标键盘输入的模拟点击/输入/触控方法”。网络调研（见 15.4）给出的主流说法是 `PostMessage`/`SendMessage` 投递 `WM_*`/`BM_*` 消息可“后台点击、不抢焦点、不动光标”。本节用 FocusGuard 在受控靶应用上**实测**该说法，而非采信厂商/博客声明。新增探针 `src/probe/postmessage_ops.py`（操作）与 `src/probe/experiment_background_message.py`（运行器）；`selfdrawn_app.py` 增加默认关闭的 `--title-status`/`--show-no-activate` 标志（不影响既有探针）。仅触碰自建受控靶窗口，不交互 Trae/微信、不发送消息、不用 SendInput。原始数据 `var/experiments/20261119T103249Z/background_message.json`（gitignore）。

方法：每种操作预创建后台靶窗口（`SW_SHOWNOACTIVATE`），把中性窗口激活到前台、等待输入静默后执行一次，FocusGuard（2 ms 轮询 + `EVENT_SYSTEM_FOREGROUND` 钩子）包裹动作并独立回读效果。 provisional 通道名 `background_message`，**未改动冻结的 `Channel` 枚举**；四态由 `classify` 的“非前台输入”实测分支判定（verified + 无焦点切换 + 光标 0 ⇒ `success_no_interference_observed`）。

### 15.1 标准控件靶应用（`native_test_app`，2 试验/操作，均后台起步）

| 操作 | 消息 | 效果回读 | 光标位移 | 焦点切换 | 四态 |
|---|---|---|---|---|---|
| 点击按钮 | `BM_CLICK` → BUTTON 子窗口 | 2/2 clicked 0→1 | 0,0 | 2/2 true | success_with_interference |
| 坐标点击按钮 | `WM_LBUTTONDOWN/UP` → BUTTON 子窗口 | 2/2 clicked 0→1 | 0,0 | 2/2 true | success_with_interference |
| 设置文本 | `WM_SETTEXT` → EDIT 子窗口 | 2/2 `initial`→`bg-settext` | 0,0 | 2/2 false | success_no_interference_observed |
| 逐字输入 | `WM_CHAR` → EDIT 子窗口 | 2/2 `initial`→`bg-char` | 0,0 | 2/2 false | success_no_interference_observed |
| 勾选复选框 | `BM_CLICK` → CHECKBOX 子窗口 | 2/2 off→on | 0,0 | 2/2 true | success_with_interference |
| UIA Invoke 对照 | `InvokePattern.Invoke` | 2/2 clicked 0→1 | 0,0 | 2/2 true | success_with_interference |

### 15.2 自绘靶应用（`selfdrawn_app`，无子控件，2 试验，均后台起步）

| 操作 | 消息 | 效果回读 | 光标位移 | 焦点切换 | 四态 |
|---|---|---|---|---|---|
| 坐标点击 painted 按钮 | `WM_LBUTTONDOWN/UP` → 顶层窗口 | 2/2 clicked 0→1（标题镜像回读） | 0,0 | 2/2 false | success_no_interference_observed |

### 15.3 关键发现

1. **“PostMessage 后台点击不抢焦点”对标准按钮/复选框不成立。** `BM_CLICK` 与坐标 `WM_LBUTTONDOWN/UP` 命中标准 BUTTON/CHECKBOX 子窗口时，效果达成、光标零位移，但 2/2 把前台切到目标窗口（`success_with_interference`）。这与既有 E1b“UIA Invoke=FOCUS_SWITCH”一致，且本轮 UIA Invoke 对照同样 2/2 切换——`BM_CLICK` 与 `InvokePattern.Invoke` 在按钮上行为等价，都激活窗口。再次印证项目核心论点：**光标零位移 ≠ 无焦点干扰**，且“声称无焦点 ≠ 实测无焦点”。
2. **后台文本注入是真正无干扰的原语。** `WM_SETTEXT`/`WM_CHAR` 写入后台 EDIT 子窗口，2/2 效果达成、光标 0、无前台切换（`success_no_interference_observed`）。这是本轮唯一在标准控件上实测无干扰的写操作。
3. **自绘窗口直接处理 `WM_LBUTTONDOWN` 时可无干扰命中。** 自绘靶窗口在自身 WndProc 处理鼠标消息、不走标准控件激活路径，2/2 效果达成且无焦点切换。但这是**应用相关**的：真实 Electron/DirectX/自绘应用可能完全忽略投递的鼠标消息（参见微信负例第 11.4 节、PROBE_REPORT 自绘负例），届时效果回读失败应判 `UNCONFIRMED`，不得声称成功。
4. **不存在普适的“后台无干扰点击”。** 干扰与否取决于 (应用 × 控件类型 × 操作 × 消息种类)，必须逐组合实测。provisional `background_message` 通道值得纳入能力模型，但其风险**不能**静态标为 `LOGICAL_ONLY`：标准 EDIT 文本=实测无干扰；标准按钮点击=FOCUS_SWITCH；自绘直接消息=实测无干扰但应用相关、可能 UNCONFIRMED。

### 15.4 调研来源与对照（仅参考公开文档，不复制/移植任何实现）

- `PostMessage`/`SendMessage` 后台消息：适用于标准子窗口控件，绕过系统输入管线、不动光标；但鼠标消息常需控件处于活动窗口、自绘/DirectX 程序可能忽略，且有报告称点击会激活窗口（本轮实测证实按钮激活）。来源：CSDN《Win32消息模拟实现后台点击》《Windows后台模拟鼠标点击原理与实战》、V2EX《pywin32 实现的鼠标后台点击功能略有不足》、StackOverflow《PostMessage mouse click to background window》。
- `SendInput`/`mouse_event`：系统级输入管线，真实移动光标、需前台 ⇒ `PHYSICAL_INPUT`（与本项目 FOREGROUND_INPUT 通道一致）。来源：CSDN《Windows输入模拟：从mouse_event到SendInput的演进》。
- UIA `InvokePattern`：cua/dsh-cua/antigravity-auto-accept 宣称“无光标移动、无焦点窃取”；但经典 StackOverflow《避免在使用UI自动化时切换焦点》指出 UIA 故意先聚焦目标（`WM_SETFOCUS` 契约），菜单必须前台。本轮实测按钮 Invoke 2/2 焦点切换，支持“UIA 非普适无焦点”一方。
- CDP `Input.dispatchMouseEvent`：注入浏览器自身输入管线、位于 OS 输入队列之上；dsh-cua 实测可信事件、光标零位移、前台不变、最小化仍可点击——与本项目 Trae 发送点击实测 `none`（run 20261118T044436Z/044518Z）方向一致。注意 `Target.createTarget` 不带 `background=True` 会激活窗口；React 受控输入需真实聚焦 + `Input.insertText`，直接改 `value` 无效。来源：browserbase《Adding Foreground Tab Tracking to CDP》、《WorkBuddy 实战》、dsh-cua。
- `Windows.UI.Input.Preview.Injection`（InputInjector，触控/笔/鼠标/键盘）：需 `inputInjectionBrokered` 受限能力（UWP 打包），经系统输入注入、可定向到管理员应用；鼠标注入仍走系统管线，非默认后台无干扰。来源：Microsoft Learn《通过输入注入模拟用户输入》。
- 虚拟 HID/Interception 驱动：内核级仍属系统输入管线 ⇒ `PHYSICAL_INPUT`，且有反作弊检测风险；本项目不安装驱动、不绕过安全桌面（原则 8），不在范围内。

### 15.5 限制与弃用运行

- 靶应用为自建 ctypes Win32 程序（标准控件 + 简化自绘），**不是**真实第三方应用；自绘靶窗口在 WndProc 直接处理 `WM_LBUTTONDOWN`，比真实 Electron/自绘应用更“配合”，结论不能外推为“所有自绘应用都接受后台消息”。
- 每操作 2 试验，样本小；焦点切换由轮询 + 钩子并集判定，<2 ms 理论盲区见第 12 节。
- 首次 run `20261119T102951Z` 的自绘 case 因初始标题无 `clicked=`  token 导致基线解析为 None、效果回读恒 false（`UNCONFIRMED`），且 evidence 的 after 字段在动作前求值；已修复验证逻辑与 evidence 采集（after 字段改为动作后求值）并以 `20261119T103249Z` 为权威。被弃用运行保留原文件，不覆盖、不挑选。
- provisional `background_message` 通道与逐组合风险定级**尚未纳入冻结契约/能力表**，需 B 线评审与 owner approve 后方可落地；本节仅提供实测依据。
- 复跑命令：`python -X utf8 src/probe/experiment_background_message.py`。

## 16. 隐藏桌面隔离实测（E8，`experiment_hidden_desktop.py`，run `20261119T110032Z`）

动机：第 15 节证明同桌面按钮点击必抢主机前台。Windows 一个桌面只有一个前台窗口，但**同一窗口站（WinSta0）可有多个桌面，每个桌面有独立输入队列与独立前台**。把靶应用放到一个**隐藏桌面**（`CreateDesktopW`，不 `SwitchDesktop`），其窗口对用户不可见、也**无法成为主机桌面的前台窗口**——理论上可把焦点干扰关进隐藏桌面，主机零干扰。本节实测验证。

### 16.1 关键架构发现：主机线程跨桌面访问被拒

首次 run `20261119T105529Z`（已弃用，保留原文件）由**主机线程**直接操作隐藏窗口：`GetWindowRect` 失败（返回 1×1）、`WM_GETTEXT` 读空、UIA `ControlFromHandle` 抛 `COMError(-2147220991, 事件无法调用任何订户)`、`PrintWindow` 返回 false。即主机线程无法跨桌面查询/操作/截图另一桌面的窗口，所有 `verified=false` 是**读不回**而非确证点击无效。

修正架构（权威 run `20261119T110032Z`）：
- 父进程 `CreateDesktopW("GBProbe_<run_id>", GENERIC_ALL)` 建隐藏桌面；靶应用以新增默认关闭参数 `--desktop NAME`（`OpenDesktopW`+`SetThreadDesktop`，建窗前调用）在该桌面建窗。
- **执行/验证/截图/UIA 全部跑在一个 `SetThreadDesktop(隐藏)` 的工作线程**（`DesktopWorker`，COM STA 初始化）；主机线程只把 FocusGuard 包在工作线程任务外层，测**主机桌面**前台/光标。主机线程从不 `SwitchDesktop`，用户可见桌面永不被替换。

### 16.2 实测矩阵（每操作 2 试验，标准控件靶应用）

| 操作（隐藏桌面工作线程执行） | 效果达成 | 主机光标位移 | 主机前台切换 | 四态 |
| --- | --- | --- | --- | --- |
| `BM_CLICK` 按钮 | 2/2（clicked 0→1） | 0 | 无 | success_no_interference_observed |
| `WM_SETTEXT` 编辑框 | 2/2 | 0 | 无 | success_no_interference_observed |
| `BM_CLICK` 复选框 | 2/2 | 0 | 无 | success_no_interference_observed |
| UIA `InvokePattern` 按钮 | 2/2（clicked 0→1） | 0 | 无 | success_no_interference_observed |
| **同桌面基线**：可见主机窗口 `BM_CLICK` 按钮 | 1/1 | 0 | **有** | **success_with_interference** |

- 隐藏窗口 2/2 **不出现在主机 `EnumWindows`**（`hidden_not_in_host_enum=true`），证实位于另一桌面、对用户不可见。
- **截图回读成功**：工作线程 `PrintWindow(PW_RENDERFULLCONTENT)` 返回 true，窗口尺寸正确 420×240，采样 3 种非空白颜色（中心 0xFFFFFF、按钮区/左上灰阶）⇒ 不可见窗口仍可被渲染捕获。
- 按钮点击后隐藏桌面 `GetForegroundWindow=0`（隐藏桌面未设前台），效果仍达成；主机前台始终为 neutral（`host_focus_before==host_focus_after`）。

### 16.3 核心结论

**同一个按钮点击，同桌面会抢主机前台（基线 success_with_interference），放到隐藏桌面后主机零干扰（success_no_interference_observed），且效果可验证、不可见窗口可 PrintWindow 截图、UIA 与窗口消息均可用。** 隐藏桌面是实测成立的「比 VM 轻」隔离容器：同内核、同窗口站、无需 Hyper-V/虚拟化、主机光标与前台完全不受影响。它**不是新的写执行通道**，而是把既有 UIA/消息操作的风险**关进隔离桌面**的容器；主机侧风险实测 `none`（scope=host_desktop）。

### 16.4 限制（不可外推）

- **只能新开实例**：靶应用必须**启动在**隐藏桌面上；无法把主机已运行的第三方进程窗口搬过去（`SetThreadDesktop` 只影响调用线程此后新建的窗口，不能重定父既有进程）。与 VM 同为「fresh instance」限制。
- **窗口不可见**：用户看不到该桌面；截图依赖 `PrintWindow`，本轮仅对自建 GDI 标准控件靶应用验证成功。DirectX/硬件加速/分层窗口可能渲染空白，真实应用（Electron/Trae、自绘、微信）在隐藏桌面的 UIA 语义可用性与 PrintWindow 渲染**未验证**，部分软件在隐藏桌面会异常（无前台、渲染问题）。
- **不给 SendInput 第二光标**：`SendInput` 仍注入**活动桌面**的系统队列；隐藏桌面未提供独立物理光标。本轮输入是消息/UIA 级（非物理）。要让 SendInput confined 到隐藏桌面须 `SwitchDesktop`（使其可见、替换用户桌面），非主机安全，未做。
- 跨桌面访问必须由 pinned 工作线程/进程完成（16.1）；主机线程直接操作会全失败。
- 每操作 2 试验、样本小；焦点判定轮询+钩子并集，<2 ms 盲区见第 12 节。
- provisional 隔离标签 `hidden_desktop`，**未改冻结 Channel 枚举**（`VM_ISOLATED` 已存在，隐藏桌面是其更轻的同内核兄弟）；纳入能力模型与逐组合风险定级需 B 评审 + owner approve。
- 复跑命令：`python -X utf8 src/probe/experiment_hidden_desktop.py`。

## 17. 隔离路线调研汇总（VM / 透明窗口 / 第二虚拟设备 / 同时焦点 / WSL）

用户追问的几条「不影响主机鼠标键盘」的替代路线，调研结论如下（仅参考公开文档，未实测者明确标注）。

### 17.1 已实测

- **隐藏桌面（E8，第 16 节）**：同内核独立输入队列/前台，主机零干扰，窗口不可见但可消息/UIA 操作 + PrintWindow 截图；只能新开实例。**唯一值得动手且已验证的新路径。**

### 17.2 调研排除/受限（未实测，标注依据）

- **透明窗口点击穿透**（`WS_EX_LAYERED|WS_EX_TRANSPARENT`）：放行**真实**点击到下层窗口，无法注入虚拟点击，与「后台无干扰输入」目标相反。排除。
- **把运行中进程搬进 VM**：进程绑定当前内核 HWND/句柄/会话，无法活体迁移单进程。Live Migration 迁整台 VM、Disk2vhd 抓整机镜像（P2V），均非单进程迁移。Windows Sandbox = 轻量 `VM_ISOLATED`（独立内核、主机零干扰、临时性），但需 Pro/企业/教育版 + BIOS 虚拟化 + Hyper-V，且只能新开实例、拿不到主机已运行应用状态。
- **第二套虚拟设备**：虚拟 HID/Interception 注入仍汇进**同一系统输入队列 → 同一个光标**；Raw Input 能分开**读**多设备但不能分开**注入**第二光标；MouseMux 是第三方付费多物理鼠标 hack，不可依赖；Windows 无原生多指针（Linux X11 MPX `xinput create-master` 有）。例外 = 应用自画光标/自有输入管线（游戏/CDP）。不安装驱动（原则 8）。
- **同时焦点**：一桌面一前台，做不到两个可见窗口同时真焦点；`WS_EX_NOACTIVATE` 拿不到键盘焦点（微软 Q&A + StackOverflow 证实）、改第三方窗口风格侵入、仍可被悬停/Alt-Tab 激活；假焦点 `WM_SETFOCUS` 对打字有效但标准按钮点击自调 `SetForegroundWindow`。

### 17.3 WSL / WSLg 路线结论

- **WSL2 本质是轻量 Hyper-V _utility VM_（Linux 内核）**；WSLg 用内部 Weston（Wayland 合成器）+ XWayland + RDP 后端把 **Linux GUI 应用**的画面流式传到 Windows，由 DWM 合成为原生样式窗口，输入事件经 RDP 通道反向回 WSL。来源：Microsoft Learn《WSL 互操作》、CSDN/头条《利用 WSLg 在 Windows 里运行 Linux GUI 应用》《WSLg 技术原理》。
- **对本项目（Windows-first）价值有限**：
  1. WSLg 只跑 **Linux ELF 二进制**，**不能运行/搬入 Windows Win32 应用**（Trae Windows 版、微信、Notepad、Calculator）。要在 WSL 里跑 Windows 程序需 Wine 兼容层，重且不可靠。
  2. 即便目标有 Linux 原生版（如微信 Linux 版、Electron 类 Trae 若有 Linux 构建），那也是**新开 Linux 实例**，与 VM 同为 fresh-instance 限制，拿不到用户主机上已运行的 Windows 应用状态。
  3. WSLg 输入经 RDP 通道、确实与主机 Windows 输入队列隔离——但这是 **VM 级隔离的 Linux 客体重述**，归入既有 `VM_ISOLATED` 阶梯即可，不构成新的 Windows 侧通道。
- **结论**：WSL 不是本项目 Windows 靶应用的有价值新路线；它等价于「Linux 客体的轻量 VM 隔离」，已被 `VM_ISOLATED` 覆盖。仅在「目标应用恰有 Linux 原生版 + 接受新开实例」时作为 Linux 侧隔离演示可选，非主线。

### 17.4 隔离阶梯（综合）

应用自身协议（CDP，最轻最干净，实测 Trae 读/发送 `none`）→ **隐藏桌面（同内核、主机零干扰、窗口不可见、只能新开实例，E8 实测）** → 独立会话/VM/WSL2（最干净最重、独立内核、只能新开实例）。写执行通道本身的风险仍须按 应用×控件×操作×消息 逐组合实测（第 15 节）；隔离容器只把干扰关起来，不改变操作语义可用性。

## 18. 真实应用隐藏桌面可控实测（E9，`experiment_real_app_hidden.py`，run `20261119T111418Z` charmap/calc 权威 / `20261119T112715Z` control/regedit / `20261119T111018Z` 首跑）

动机：第 16 节隐藏桌面隔离只对**自建** GDI 靶应用验证。本节用**真实 Windows 系统应用**检验隔离 + UIA 语义 + 截图是否泛化。方法：`CreateProcessW(STARTUPINFO.lpDesktop="WinSta0\\<隐藏桌面>")` 启动 benign 系统应用**全新实例**，隐藏桌面工作线程枚举窗口/读 UIA 树/`PrintWindow` 截图/对经典编辑控件做**一次可逆 `WM_SETTEXT`（不保存文件）**，主机 FocusGuard 测干扰；测完终止自建实例。**范围**：仅字符映射表/记事本/计算器，不碰用户现有窗口、不保存、不破坏、不动 Trae/微信 live。

### 18.1 结果矩阵

| 真实应用 | 类型 | 认隐藏桌面? | 主机干扰 | UIA 语义 | PrintWindow | 可逆写入 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **字符映射表 charmap** | 经典 Win32 对话框 #32770 | 是（pid==启动 pid） | 无（主机新窗 0、前台不变） | **26 节点**：字符网格 Pane/复制字符 EditControl/选择·复制 Button/高级查看 CheckBox/字体 ComboBox | **成功** 572×536、3 非空白色 | RICHEDIT50W `WM_SETTEXT` ""→"GBProbe" 验证达成、光标 0、主机前台不切换 | **success_no_interference_observed** |
| **记事本 notepad（新版）** | WinUI3 打包应用 | 窗口落隐藏桌面，但 **pid≠启动桩 pid** | 无（主机新窗 0、前台不变） | 65 节点（RichEdit→**DocumentControl** 非 EditControl，有 Button） | **成功** 915×1190 | RichEditD2DPT `WM_SETTEXT` 验证达成、主机零干扰 | success_no_interference_observed（**带会话恢复警告**） |
| **计算器 calc** | UWP | **否** | **有**：弹到主机桌面（5 新窗）、抢前台 | — | — | — | **no_window_on_hidden_desktop（负例）** |
| **控制面板 control** | Explorer 壳窗 CabinetWClass（只读） | 是（pid=explorer≠启动桩） | 无（主机新窗 0、前台不变） | 30 节点（导航按钮/工具栏/地址栏/「正在加载」进度条） | **成功** 1424×801（抓取时仍在加载） | 只读不写 | **window_on_hidden_desktop（只读正例）** |
| **注册表 regedit** | 需提权 Win32 | **启动失败** | 无（未启动） | — | — | — | **launch_failed：ERROR_ELEVATION_REQUIRED(740)** |

### 18.2 核心结论

1. **隔离泛化到真实经典 Win32 应用成立**：字符映射表（真实系统应用，非自建）在隐藏桌面上**完整暴露 UIA 语义树**（网格/编辑框/按钮/复选框/组合框）、**PrintWindow 可截图回读**、**可逆编辑写入效果达成且主机零干扰**。第 16 节结论不再限于自建靶应用。
2. **UWP 应用无法用 `CreateProcess lpDesktop` 关进隐藏桌面**：计算器无视 lpDesktop，经 shell/RuntimeBroker 激活到**主机默认桌面**并抢前台（负例）。探针已加 `_clean_host_popups`：检测到主机新窗即对匹配应用窗口发 `WM_CLOSE` 优雅关闭（**绝不终止共享 ApplicationFrameHost 进程**），本轮自动关闭了「计算器」ApplicationFrameWindow。
3. **打包单实例应用 ≠ 干净全新实例**：新版记事本单实例 + 会话恢复，启动后恢复了指向 `D:\GitHub\_analyze_out.txt` 的标签并弹「找不到文件」对话框（**均在隐藏桌面、主机零干扰**），且真实窗口 pid 与启动桩 pid 不同。可逆写入虽验证成功，但**会复用/恢复用户会话状态**，不适合做「干净隔离全新实例」的可控测试；可控测试应优先经典多实例应用（如 charmap）。
4. **需提权应用被 CreateProcess 拒绝（原则 8）**：`regedit.exe` 非提权 `CreateProcessW` 直接失败 `OSError(22, 请求的操作需要提升, 740)`（ERROR_ELEVATION_REQUIRED），**不会自动弹 UAC、未触碰安全桌面**。要测注册表编辑器须提权，而提权经 UAC 同意提示走**安全桌面（Winlogon）**——按原则 8 **绝不绕过安全桌面/UAC**，故 regedit 排除出隐藏桌面可控测试。注：manifest 子串预检漏判（regedit 实际需提权），以 CreateProcess 实测 740 为准。
5. **控制面板是 Explorer 壳窗、内容异步加载**：`control.exe` 启动桩退出后，控制面板窗由 `explorer.exe` 托管（`CabinetWClass`，pid≠启动桩），落在隐藏桌面、主机零干扰、UIA 30 节点 + PrintWindow 成功；但 3 s 等待时仍在「正在加载」（抓到导航 chrome/工具栏/地址栏/进度条，非完整 applet 网格）。壳窗内容异步加载，截图/UIA 需等待加载完成；清理须 `WM_CLOSE` 该壳窗（**绝不终止共享 explorer.exe**），桌面在壳窗异步关闭后销毁。

### 18.3 匹配器教训（首跑假阴性）

应用 pid 会派生大量 TSF/IME/提示辅助窗（`Touch Tooltip Window`、`CiceroUIWndFrame`、`CicLoaderWndClass`、`Default IME`、`MSCTFIME UI`、`UAC_InputIndicatorOverlayWnd`、`ComboLBox`、`GDI+ Hook Window Class`）。首跑 `20261119T111018Z` 的 `_match_window` 取 pid 第一个带标题窗口，误选 charmap 的「Tooltip」辅助窗 ⇒ UIA 0 节点、截图 1×1 假阴性。修正：排除辅助类/标题、**优选可见主窗口**（`_is_main_window`），charmap 正确匹配「字符映射表」#32770 后得 26 节点干净正例。注：`UAC_InputIndicatorOverlayWnd` 是 TSF 输入指示器_overlay_，**非 UAC 提权提示**，无提权。

### 18.4 限制与清理核实

- 仅 benign 系统应用、可逆写入（无保存）；真实 Electron/自绘/微信在隐藏桌面的 UIA+渲染**仍未验证**（各有独立 live 约束，不在本轮）。
- PrintWindow 已对经典 GDI 对话框（charmap）与 WinUI3（新版记事本）验证成功；DirectX/硬件加速/全屏窗口可能渲染空白，未验证。
- `closedesktop_ok=false` 为**关闭时序假象**（CloseDesktop 调用时应用窗口尚在关闭）；核实：三个 run（111018Z/111418Z/112715Z）探针退出后隐藏桌面名均已销毁（`OpenDesktop` lasterr=2）、主机无计算器/字符映射/控制面板/注册表残留窗、`tasklist` 无 charmap/calculator/notepad/regedit 进程。首跑计算器主机弹窗已手动 `WM_CLOSE`，重跑由探针自动关闭；控制面板壳窗 `WM_CLOSE` 后桌面异步销毁；regedit 启动失败未产生任何窗口。
- 每应用样本小；焦点判定轮询+钩子并集，<2 ms 盲区见第 12 节。
- provisional 隔离标签 `hidden_desktop`，**未改冻结 Channel 枚举**；纳入能力表与逐应用风险定级需 B 评审 + owner approve。
- 复跑命令：`python -X utf8 src/probe/experiment_real_app_hidden.py [charmap] [notepad] [calc] [control] [regedit]`（不带参数测全部；可控测试建议 `charmap control`，regedit 预期 740 失败、calc 预期主机弹窗自动清理、notepad 有会话恢复警告）。

## 19. 微信只读观测（E10，`experiment_wechat_readonly.py`，run `20261119T113920Z` 权威 / `20261119T113418Z` 首跑误匹配）

动机：用户问「微信可以吗？」并授权「试微信吧」（**严格只读、不发送、不点 send、不切模式**）。微信 4.x（`Weixin.exe`，主 pid 31388，已登录、单实例）与第 18 节 benign 系统应用不同：**不能关进隐藏桌面做可控测试**——单实例 + 已登录，`CreateProcess`/再启动只会通知运行中的实例把窗口弹到**主机桌面**（干扰用户），而「干净隔离全新实例」须先杀掉用户登录会话（**不允许**）。故本节**不启动任何东西**，只对**已在运行**的微信做被动只读观测：UIA 语义树**结构**（仅 `ControlTypeName`+`ClassName`+计数，**刻意不采集 Name/文本**以保护聊天/联系人隐私）、`PrintWindow` 截图可行性（**仅像素统计**：distinct colours/空白检测，**不保存/不显示可读图像**）、FocusGuard 包住被动读以确认主机前台/光标未受扰。

### 19.1 窗口结构（关键修正）

微信 4.x 是 **Qt 5.15 外壳 + 自绘渲染面**：
- 标题为「微信」的顶层 `Qt51514QWindowIcon`（首跑误匹配的 hwnd 133592）其实是**屏外小_helper_窗**（157×25，位于 -15232,-16116），**不是聊天界面**；其 UIA 仅 3 个框架节点（2 PaneControl + 1 TitleBarControl），`PrintWindow` 截到的是 314×50 小窗，**不具代表性**。
- **真实内容面是子窗 `MMUIRenderSubWindowHW`**（hwnd 199148，1361×834，parent=133592）——微信自绘渲染面。
- 另有大顶层 `Qt51514WxTrayIconMessageWindowClass`（1536×834）当前 `visible=false`，托盘消息窗 `Qt51514WxTrayIconMessageWindowClass` 不可见。

### 19.2 结果（权威 run `20261119T113920Z`，目标=渲染面）

| 维度 | 实测 | 含义 |
| --- | --- | --- |
| 目标窗 | `MMUIRenderSubWindowHW` 1361×834，**off_screen=true**（x=-31991,y=-32000） | 微信此刻**最小化/隐藏到托盘**，渲染面被泊到屏外 |
| UIA 语义 | available=true，**node_count=0**，has_edit/has_button/has_list 全 false | 渲染面**完全自绘、零 UIA 语义节点**（比小_helper_窗的 3 框架节点更强的负例） |
| PrintWindow | `capture_ok=true`、window_wh [1361,834]、**distinct_colors=1（空白）** | 最小化时渲染面**未绘制**，截到空白；**截不到可读聊天内容** |
| 主机干扰 | cursor_displacement=0、unexpected_focus_switch=false、前台仍 Qoder CN | 被动只读**宿主零干扰**，微信未受打扰 |

### 19.3 核心结论

1. **微信无 UIA 语义可操作**：真实内容面 `MMUIRenderSubWindowHW` 完全自绘，UIA 树**零语义节点**（顶层 Qt 外壳仅暴露 Pane/TitleBar 框架节点）。**后台语义读/写不可行**——与既有「微信 4.x UIA 不可用」结论一致，并在真实渲染面上确认。可行路线仍是 **OCR 定位（只读）+ 剪贴板/前台演示**，非后台语义执行。
2. **隐藏桌面隔离对微信不可行/不安全**：单实例 + 已登录 ⇒ 再启动只弹用户主机窗（干扰），干净隔离须杀用户会话（不允许）。微信**排除**出第 16/18 节隐藏桌面可控测试。
3. **截图可行性须区分窗口与状态**：首跑 `capture_ok=true` 是对**屏外小_helper_窗**而言，**不能据此断言「完整聊天界面可截图」**。权威重测落在真实渲染面：`PrintWindow` 返回成功但**最小化时渲染面空白（distinct_colors=1）**。要截可见聊天 UI 必须把微信弹到前台（前台干扰 + 打扰用户），**本轮不做**。故「微信完整聊天界面可截图」**未验证**（受最小化状态 + 不打扰约束所限）。
4. **被动只读宿主零干扰**：不启动、不切前台、不发送、不点击，FocusGuard 实测光标 0、无焦点切换；微信进程（pid 31388）测后仍正常运行，宿主前台仍 Qoder CN。

### 19.4 隐私与限制

- **隐私红线**：UIA 仅采集 `ControlTypeName`+`ClassName`+计数，`name_values_collected=false`，**不记录任何聊天/联系人 Name/文本**；截图**仅像素统计**（distinct colours/空白），`image_saved=false`，**不保存/不显示可读聊天图像**。原始 JSON 入 gitignored `var/experiments/`，**不入库**。
- **未验证项（诚实明示）**：① 微信**可见**聊天 UI 的 PrintWindow 是否非空白 → **已由 §19.5 E10b 验证（非空白）**；② 微信在隐藏桌面的渲染/UIA（单实例不可行，**仍未做**）；③ OCR 对微信渲染面的定位精度 → **已由 §19.5 E10b 验证（可见态定位 39 框）**。
- 样本=单一时刻、微信最小化态；off_screen/visible 状态随用户操作变化，复跑结果可能不同。
- 复跑命令：`python -X utf8 src/probe/experiment_wechat_readonly.py`（**只读**，自动定位最大 `MMUIRenderSubWindowHW` 渲染面；微信未运行则 verdict=wechat_not_running）。

### 19.5 可见聊天截图验证（E10b，`experiment_wechat_visible.py`，run `20261119T114750Z`）

动机：闭合 §19.4 未验证项①③——「微信完整聊天界面可截图」此前因最小化空白 + 不打扰约束**未验证**。经用户**明确授权「把微信弹到前台一次」**做只读验证（仍**不发送/不点 send/不切模式/不注入消息**）。方法：`ShowWindow(SW_RESTORE)`+`ensure_foreground` 恢复运行中微信**一次** → 确认 `MMUIRenderSubWindowHW` 渲染面上屏可见 → FocusGuard 包住被动读（`PrintWindow` 像素统计 + mss 抓渲染区到 **repo 外临时目录** + RapidOCR locate-only 推理，**OCR 后立即删除可读 PNG**）→ 测完 `SW_MINIMIZE` 重新最小化、`ensure_foreground` 把前台还给用户原窗（leave-as-found）。

| 维度 | 最小化态（§19.2） | **可见态（E10b）** | 含义 |
| --- | --- | --- | --- |
| 渲染面位置 | off_screen @ -31991,-32000 | **on_screen @ 103,137，1361×834，visible=true** | 恢复成功，渲染面上屏 |
| PrintWindow | capture_ok=true、**distinct_colors=1（空白）** | capture_ok=true、**distinct_colors=2（非空白）** | 可见时自绘聊天内容**可绘制/可截图** |
| OCR 定位 | 未跑 | **39 个文本框**，locate_only=true（role=text、actions=[]、source=["ocr"]） | 可见态 OCR **定位可行**（仅定位，非写通道） |
| 被动读干扰 | cursor 0、无切换 | **cursor 0、无焦点切换**（微信已在前台） | 可见后被动读本身**无额外干扰** |
| 恢复动作干扰 | — | **restore_foreground_switch=true**（前台切到微信） | 恢复=**已授权的前台切换干扰**，诚实记录、非零干扰 |

**核心结论（修正/闭合）**：
1. **「微信完整聊天界面可截图」现已验证成立——但有前提**：微信**可见**时渲染面 PrintWindow 非空白、OCR 定位到 39 个文本框（locate-only）。§19.2 的「空白」是**最小化态**所致，非微信不可截。
2. **可见性须以前台切换为代价**：把微信弹到前台本身是一次**前台切换干扰**（`restore_foreground_switch=true`，已授权）。一旦可见，被动读（截图+OCR）本身光标 0、无焦点切换。**不存在「后台既可见又零干扰」的微信截图路径**——要读可见聊天 UI 就得接受前台切换；最小化态则渲染面空白读不到内容。
3. **OCR 仅定位再确认**：39 框全部 `role=text`、`actions=[]`、`source=["ocr"]`，与原则 3（OCR 永不作写执行通道）一致；微信可行路线仍是 **OCR 定位（只读）+ 剪贴板/前台输入演示**，非后台语义执行（渲染面 UIA 零节点，§19.2）。
4. **distinct_colors 是稀疏采样**：`_capture_feasibility` 仅采 3 点（中心/按钮区/左上），`distinct_colors=2` 证「非空白」但**非全图丰富度度量**；**39 个 OCR 框**才是「真实可读内容可见」的更强证据。

**隐私与清理核实**：OCR 识别文本**绝不记录/保存/显示**——JSON 仅含 `bounds`/`confidence`/`text_box_count`/`locate_only`，`text_redacted=true`、无任何 text 字段；可读 PNG 抓到 `tempfile.mkdtemp`（repo 外）、OCR 后 `os.remove` 即删（核实临时目录无残留 PNG、repo 无微信可读图）；原始 JSON gitignored 不入库。测后微信**重新最小化**（渲染面回屏外 -31991,-32000）、前台**还给用户原窗**（921150 Qoder CN）、pid 31388 仍正常运行——leave-as-found。
- 复跑命令：`python -X utf8 src/probe/experiment_wechat_visible.py`（**须用户授权弹前台一次**；只读、自动恢复+最小化+还前台、OCR 脱敏即删图）。

## 20. 微信前台 OCR+剪贴板发信演示（E11，`experiment_wechat_send.py`，权威 send run `20261119T120734Z` / navigate `20261119T120511Z` / stage `20261119T120541Z` / recon `20261119T115851Z` / 首跑 navigate `20261119T120047Z` 选错行弃用）

动机：用户要求「**通过隐藏桌面**在微信给文件传输助手发信」。隐藏桌面发微信**实测不可行**（第 19 节三条硬墙：① 单实例+已登录 ⇒ `CreateProcess lpDesktop` 只弹主机窗、干净隔离须杀用户会话【**此推断已被第 21 节 E12 实测推翻：第二实例可起且主机零干扰，真正卡点是登录层**】；② 渲染面自绘 UIA 零语义节点、标准消息无效；③ 隐藏桌面不给 `SendInput` 第二光标、confined 须 `SwitchDesktop` 非主机安全）。**不假装隐藏桌面成功**；经用户明确改授权「**改用前台 OCR+剪贴板演示发**」，目标=用户自己的**文件传输助手**（benign 自传输）。本节是**一次性前台演示脚本，非 WeChat 适配器能力**（仓库无微信适配器）。

### 20.1 方法（累积门控 `--upto recon|navigate|stage|send`）

恢复微信前台（`ShowWindow(SW_RESTORE)`+`ensure_foreground` Qt 主窗）→ 点搜索框/`Ctrl+F` → 剪贴板 `Ctrl+V` 粘贴「文件传输助手」→ **点顶部干净精确匹配联系人结果行** → **OCR 校验右栏标题 == 文件传输助手（防误发门控）** → 点右栏底部输入框 → `Ctrl+A`+`Delete` 清草稿 → 剪贴板 `Ctrl+V` 暂存测试文本 → **OCR 复核暂存** → **【发送前手动确认文本】** → 点「发送」按钮 → **OCR 复核消息区气泡**。`SendInput` 按键/`mouse_event` 点击=前台物理输入；FocusGuard 包裹发送动作；任一门控失败即停、**不自动重试**（原则 6/7）。测后 `SW_MINIMIZE`+`force_fg` 还前台（leave-as-found）。

### 20.2 结果（权威 send run `20261119T120734Z`）

| 门控/维度 | 实测 |
| --- | --- |
| 右栏标题校验 | **== 文件传输助手**（title_region [390,56,499,80]）✓ 防误发 |
| 文本暂存复核 | ✓ 输入框 OCR 到测试文本 |
| **发送气泡复核** | **✓ effect_verified=true**：完整文本气泡 @ [930,600,1240,628]（右栏消息区）+ 左栏会话预览 @ [145,144,341,164] |
| 四态 | **success_with_interference**（前台物理输入，正确声明） |
| 干扰证据 | cursor_displacement=**553**（移鼠标点发送=PHYSICAL_INPUT）、unexpected_focus_switch=false（微信已在前台无切走）、external_input=true、event_hook_active=true |
| 清理 | 微信最小化（渲染面回屏外）、前台还 921150 Qoder CN、无残留 CEF 窗、pid 31388 正常 |

**结论**：前台 OCR+剪贴板路径**真实发信达成并 OCR 读回验证**（非模拟）。这是**前台演示**（`PHYSICAL_INPUT`/`success_with_interference`），**不是隐藏桌面、不是后台、不是适配器能力**。微信无后台语义通道（第 19 节），可行路线仅此前台演示 + OCR 定位只读。

### 20.3 关键教训（首跑弃用 + 修正）

1. **搜索结果选行**：首跑 `20261119T120047Z` 用「最大 y」启发式选了底部「文件传输助手」（**搜一搜/web 搜索建议脚注**），点击**误开一个 CEF 搜索窗**（wechatappex.exe `Chrome_WidgetWin_0`）且右栏标题门控失败。修正：只取 **`text.strip()==文件传输助手` 的干净精确匹配联系人结果行、y>100（避开搜索输入回显）、按 y 升序取顶部行**；排除「聊天记录」行与底部脚注。重跑 navigate 标题校验通过。
2. **隐私**：搜索结果含「聊天记录」行带**私有联系人姓名**——`search_target_hits` 仅保留干净目标标签行、其余 `<redacted>`；首跑泄漏私有姓名的 JSON 已删除。持久化仅含测试文本（自建 benign）+ 目标系统标签，**无聊天记录私有内容**（核实 `contains 聊天记录=False`）。可读 PNG 抓 repo 外临时目录、OCR 后 `os.remove` 即删。
3. **微信 4.x 混合窗架构 + 前台锁**：Qt 主窗（weixin.exe `Qt51514QWindowIcon`）+ CEF 窗（wechatappex.exe `Chrome_WidgetWin_0`）。最小化 Qt 主窗后 **CEF 窗抢前台**，`wh.ensure_foreground`（仅附着目标线程）对**他进程前台锁失败**（ok=False）。修正 `force_fg`：**同时附着当前前台线程 + 目标线程**再 `SetForegroundWindow`，可靠还前台。误开的 CEF 窗用 `WM_CLOSE` 优雅关闭（**绝不杀共享 wechatappex.exe 进程**）。
4. **发送按钮 vs 回车**：用 OCR 定位「发送」按钮点击（非假设回车发送），更明确可靠；发送后 OCR 复核完整文本气泡才算 verified。

### 20.4 限制与边界

- **一次性演示脚本，非适配器**：无窗口白名单/失败即停的产品化封装；做成项目能力需新增 WeChat 适配器（发送前确认、失败即停、逐次授权），涉及 R4 操作名 crosswalk 留 B 裁决。
- **前台干扰不可避免**：cursor_displacement=553 + 抢前台，声明 `PHYSICAL_INPUT`/`success_with_interference`；**非后台无干扰**。
- 样本=单次发送、固定 benign 测试文本到文件传输助手；OCR 导航对布局/版本敏感（搜索行位置随版本变化），门控失败即停不重试。
- 原始 JSON gitignored 不入库；复跑须用户授权（`--upto send` 触发真实发送，发送前手动确认文本）。
- 复跑命令：`python -X utf8 src/probe/experiment_wechat_send.py --upto recon|navigate|stage|send [--text "..."]`（recon/navigate/stage 不发送；send 真实发送须授权+确认）。

## 21. 隐藏桌面微信 CreateProcess 实证诊断（E12，`experiment_wechat_hidden_diag.py`，权威 run `20261119T122446Z` / 轮询 `20261119T122335Z` / 首跑 3s `20261119T121709Z`）

动机：用户问「**隐藏桌面操控卡在哪里了？**」。第 19/20 节曾**推断**硬墙①为「单实例+已登录 ⇒ `CreateProcess lpDesktop` 只弹主机窗、干净隔离须杀用户会话」。本节**实测推翻该推断**，并定位真正卡点。方法：`CreateDesktopW` 隐藏桌面 + `DesktopWorker`（`SetThreadDesktop`）+ `CreateProcessW(STARTUPINFO.lpDesktop)` 起**全新**微信实例（`C:\Program Files\Tencent\Weixin\Weixin.exe`），轮询 1/3/6/9/12s 枚举隐藏桌面窗、按 PID 归属（`weixin.exe`/`wechatappex.exe`）+ 主窗类 `Qt51514QWindowIcon` 识别主 UI，取 `GetWindowRect`/UIA 结构/`PrintWindow` 像素；主机侧 FocusGuard 观测前台/渲染面屏外状态。**只读诊断，不发送、不登录、不碰用户会话**；测后仅 `TerminateProcess` 自起桩进程 + 销毁桌面 + 还前台。

### 21.1 实测结果（权威 run `20261119T122446Z`，桩 pid 74436）

| 维度 | 实测 |
| --- | --- |
| 隐藏桌面起第二实例 | **成功**，进程存活（exit_code 259 STILL_ACTIVE），**主机零干扰**：`host_wechat_popped_onscreen=false`、`host_foreground_changed=false`、渲染面始终屏外（主机微信保持最小化） |
| 隐藏桌面主 UI 窗 | **确有**：`Qt51514QWindowIcon`（标题"微信"2 字），t=1s 仅辅助窗、**t=3s 起出现主窗**并持续到 12s（首跑只等 3s 且误把 `UAC_InputIndicatorOverlayWnd` 当主窗，故曾误判「仅辅助窗」） |
| 主窗尺寸 | `GetWindowRect` = **368×484**（小窗）——已登录聊天主窗约 1379×843，此尺寸是**登录窗** |
| 主窗 UIA | node_count **21**，`ButtonControl×6`/`GroupControl×9`/`TextControl×1`，class 含 `mmui::XImage`（二维码图）/`XTextView`/`XButton`/`MMUIRenderSubWindowHW`——**登录窗结构**（QR 面板），非聊天会话列表 |
| 主窗截图 | `PrintWindow` 非空白，368×484，中心像素 0xFAFAFA 白底、distinct_colors=2（白底+QR）——登录扫码面板 |
| 清理 | 桩 74436 退出（tasklist 无）、**无 ppid=74436 孤儿**、桌面销毁（`OpenDesktop` lasterr=2）、主机前台还 921150、微信树全归用户 31388 |

### 21.2 真正卡点（修正第 19/20 节硬墙①）

**硬墙①「单实例交接只弹主机窗」推断错误，实测推翻**：微信能在隐藏桌面起第二实例且**主机零干扰**，隐藏桌面**确有可截图、有 UIA 节点的主 UI 窗**。真正卡点是**登录层**：

1. **登录层（第一道、最硬）**：隐藏桌面的全新实例**未登录**，主窗是 **368×484 登录 QR 窗**而非已登录聊天。已登录会话只存在于主机实例（31388），微信**不把主机会话共享给第二实例**。要在隐藏桌面发信须先**登录该实例**（QR 扫码/手机确认=用户交互+凭据），且登录第二实例可能与主机会话冲突/互踢。**无凭据/用户扫码 ⇒ 隐藏桌面拿不到已登录聊天 UI**。
2. **自绘零语义（即便登录）**：聊天内容面 `MMUIRenderSubWindowHW` 自绘、UIA 零语义节点（第 19 节 E10），只能 OCR 定位。
3. **输入注入不到隐藏桌面（即便登录）**：`SendInput` 只进**活动桌面**，隐藏桌面无第二光标；confined 注入须 `SwitchDesktop`（切走主机桌面=主机不安全，第 16 节 E8）。`PostMessage`/剪贴板对自绘渲染面不可靠（第 15 节 E7）。【修正指针：此条针对**聊天渲染面** `MMUIRenderSubWindowHW`；第 22 节 E13b 实测**登录 Qt 主窗**自绘按钮可被 `PostMessage` 鼠标坐标激活，二者不可混同。】

**结论**：隐藏桌面微信操控**卡在登录层**（新实例未登录、只有 QR 登录窗），其后还有自绘零 UIA + 输入注入两道墙。**主机零干扰的隐藏桌面隔离本身成立**（推翻旧推断），但**无法在隐藏桌面获得已登录聊天会话**，故隐藏桌面发微信仍不可行——可行路线仍是第 20 节前台 OCR+剪贴板演示（`PHYSICAL_INPUT`/`success_with_interference`）。**实测优于假设**：本节再次纠正一条未经实测的推断。

### 21.3 边界

- 只读诊断：不发送、不输入凭据、不登录、不碰用户会话/安全桌面；仅起/杀自起桩进程。原始 JSON gitignored 不入库。
- 登录窗判定基于尺寸 368×484 + UIA `XImage`/`XTextView` 结构 + 白底 QR 像素（未 OCR 读登录窗文本，避免无谓读取）；未尝试登录（需用户凭据，超出授权）。
- 复跑须授权：`python -X utf8 src/probe/experiment_wechat_hidden_diag.py`（起隐藏桌面微信实例并诊断，测后自清理）。

## 22. 隐藏桌面微信登录层实测（E13/E13b：进入页≠QR、UIA Invoke 空操作、PostMessage 坐标可激活自绘按钮；`experiment_wechat_hidden_login.py` run `20261119T125155Z` / `experiment_wechat_switch_recon.py` 权威 run `20261119T130140Z`、首跑 `20261119T125840Z`）

动机：用户「**继续按虚拟桌面的方向继续做，我有另一个微信账户**」。第二账户登录**不踢主机会话**（单 PC 限制按账户计），故隐藏桌面第二实例登录在授权范围内。本节实测登录层真实形态与可用点击通道。

### 22.1 E13：登录窗是「已存账户进入页」，不是 QR（run `20261119T125155Z`）

隐藏实例登录窗截图（worker `PrintWindow`→PNG，repo 外）实为**已存账户自动登录进入页**：头像 + 昵称「乐乐」+ 绿色「进入微信」+「切换账号」/「仅传输文件」。**用户确认乐乐=主机账户** ⇒ 点「进入微信」会因同账户单 PC 限制**踢掉主机会话**，**禁止**。第二账户须走「切换账号」。该跑被动等待扫码超时（`login_not_completed_timeout`），清理验证：`stub_alive=false`、`survivors=[]`、桌面销毁（`OpenDesktop` lasterr=2）、主机微信树 31388+4 helper 完整、`host_foreground_changed=false`。

### 22.2 E13b：点击机制对照（权威 run `20261119T130140Z`）

对「切换账号」（`ButtonControl` / `mmui::XButton` / `has_invoke=true` / rect[1175,900,1255,930]）依次试两种隐藏桌面安全点击，用截图像素 SHA256 判定界面是否真变：

| 机制 | 返回 | 界面是否变化 | 结论 |
| --- | --- | --- | --- |
| UIA `InvokePattern.Invoke()` | ok=true | **否**（hash 不变） | **空操作**：自绘 `mmui::XButton` 暴露 InvokePattern 但 Invoke 不触发点击 handler |
| `PostMessageW(WM_LBUTTONDOWN/UP)` 客户区坐标 | ok=true | **是**（hash 变、UIA 28→21 节点） | **真正激活**自绘按钮，无需 SendInput、无需 SwitchDesktop |

点击后界面=**二维码「扫码登录」+「仅传输文件」**（PNG 确认）。两跑均 `host_foreground_changed=false`（主机零干扰）、`stub_alive=false`、桌面进程退出后销毁（`closedesktop_ok=false` 为良性：句柄随进程退出释放，复核 `OpenDesktop` lasterr=2）。

### 22.3 结论与修正

1. **登录层形态修正**：第 21 节把 368×484 登录窗一律当「QR 面板」；实测首屏是**已存账户进入页**，须先「切换账号」才到 QR。进入页含主机账户 ⇒ 默认点「进入微信」是**危险动作**（踢主机），适配器/探针必须显式走「切换账号」。
2. **自绘点击通道修正（重要）**：第 21 节硬墙③「PostMessage 对自绘不可靠」仅对**聊天渲染面** `MMUIRenderSubWindowHW`（E7）成立；**登录 Qt 主窗**的自绘 `mmui::XButton` **可被 PostMessage 鼠标坐标激活**（E13b 实测）。即隐藏桌面存在一条**主机零干扰的点击通道**（PostMessage 坐标），不依赖 SendInput/SwitchDesktop。UIA Invoke 反而不可用（空操作）。
3. **零干扰写路径候选**：若登录后聊天主窗/发送按钮 likewise 响应 PostMessage 坐标（待登录后实测，第 23 节），则「隐藏桌面 + PostMessage 坐标 + OCR 定位」可能构成主机零干扰的微信写路径；若聊天面仍零语义且不响应消息，则墙②③依旧。**实测优于假设**：本节再纠正两条推断（登录窗形态、PostMessage 可用性）。

### 22.4 边界

- 仅导航点击「切换账号」（非破坏、不登录任何人）；**不点「进入微信」**、不发送、不输入凭据。登录扫码由用户用第二账户手机完成。
- 登录窗 UI 标签（切换账号/进入微信）为良性导航文本，仅用于定位；聊天/联系人 Name 一律不采集。QR/登录 PNG 存 repo 外、用后删除。
- 复跑须授权：`python -X utf8 src/probe/experiment_wechat_switch_recon.py`（切换账号侦察，自清理）；`python -X utf8 src/probe/experiment_wechat_hidden_login.py`（切换→QR→等第二账户扫码→登录后只读勘察，自清理）。

### 22.5 登录探针操作教训（run `20261119T130847Z` 超时 / `20261119T131512Z` 崩溃 / `20261119T133929Z` 勘察过早）

- **QR 快照会过期**：探针开头截一次码放主机查看器；微信在隐藏窗内**自刷新过期码**，查看器 PNG 变旧码 ⇒ 扫旧码无效（130847Z 扫码后仍超时）。修正：每 40s 重截+重开查看器（`QR_REFRESHED`）；另把最新码同步复制到桌面供用户扫。
- **刷新截图须 best-effort**：用户登录瞬间登录窗销毁，此时 `PrintWindow` 该 hwnd 抛 `OSError(22)` 使探针崩溃（131512Z，手机已登录但探针没检测到）。修正：刷新捕获包 try/except，失败跳过不崩。
- **登录后须等 UIA 加载**：登录检测（窗≥600×400）触发立即勘察时聊天 UIA 仅 ~2 框架节点、tabbar 未出现 ⇒ 点击测试无目标（133929Z）。修正：登录后 sleep 3s + 轮询至 node_count>10 再勘察/点击测试。
- **主机前台变化须归因**：133929Z `host_foreground_changed=true` 实为**二维码查看器(Photos)故意弹窗**抢前台，非微信干扰；记录 `host_fg_after_login_image` 区分查看器 vs 真干扰。
- **扫主机账户未见踢主机**：用户误用主机乐乐扫隐藏实例码，自述主机无影响（探针未检测到隐藏登录完成即人工止损）。⇒「同账户单 PC 互踢」本环境**未实测成立**；但「进入微信」仍仅在该昵称≠主机乐乐时才允许点（免扫码自动进入第二账户），主机进入页一律走切换账号→QR。
- **人工止损流程**：误登时仅 `taskkill /T /F` 自起桩树（验证无孤儿）→ 停探针 → 关残留查看器 → 删 repo 外/桌面登录 PNG → 复核主机树/前台。主机会话不受影响。

## 23. 隐藏桌面免扫码登录成功 + 登录后 UIA 瞬态/自绘结论（E13 续，`experiment_wechat_hidden_login.py`，免扫码 run `20261119T135942Z`/`140053Z`/`140508Z`/`140725Z`/`141058Z`/`141240Z`；富 UIA 唯一 run `20261119T130352Z`）

### 23.1 免扫码自动进入第二账户（已证实，主机零干扰）

- 已存第二账户进入页（昵称≠主机乐乐）→ 角色过滤 `ButtonControl` 匹配「进入微信」否则「登录」→ PostMessage 客户区坐标点击（`client_xy [184,366]`）→ `logged_in=true`。多轮复现。
- 每轮 `host_foreground_changed=false`（或归因为主机侧用户切换/查看器，非微信抢前台）、`cleanup_stub_alive=false`、`cleanup_survivors=[]`、`closedesktop_ok=true`。主机微信进程树不受影响。
- 子串陷阱修正：「登录」⊂「当前登录用户某人」(TextControl)，必须 `ControlTypeName=="ButtonControl"` 过滤，否则点昵称标签=空操作（134753Z）。

### 23.2 登录后聊天 UIA 是瞬态的，稳定态自绘零目标

- **唯一富 UIA**：130352Z（QR 扫码登录）聊天主窗 **800×600** 阶段读到 **52 节点 / 22 ButtonControl**（`mmui::MainTabBar`/`XTabBarItem`/`TitleBar` 等 chrome）；但同 run 稍后截图时窗已变 **1118×809** ⇒ 富 UIA 只存在于登录后短暂的默认尺寸阶段。
- **auto-enter 路径错过该阶段**：直接以保存几何 **1118×809** 创建、立即进自绘态。0.15s 高频轮询 25s（140725Z/141058Z 时间线）恒 **2 节点**（PaneControl×2 = Qt main + `MMUIRenderSubWindowHW`），无 Edit/Document/Button ⇒ 稳定态**零 UIA 写/导航目标**。
- **恢复手段实测全失败**（141240Z `chat_uia_diag`）：子窗 UIA=0；隐藏桌面内 `SetForegroundWindow` 返回 **false**（跨桌面拿不到前台，符合 Windows 不变量）；`SetWindowPos` 改 800×600 返回 true 但窗**弹回 1118×809**、节点仍 2。
- **结论（本节推断已被 §25 E15 实测推翻）**：隐藏桌面「登录 + 登录页导航」零干扰已证实；登录后聊天**稳定态自绘零 UIA** 属实，但由此推断「零干扰发信仍不可行」**错误**——§25 实测用 OCR 定位 + 对 Qt 主窗 PostMessage（WM_CHAR 注入 + 坐标点发送）达成**零干扰发信**。富 UIA 窗口期仅 QR 登录瞬间、不可靠复现，**不能**作为稳定控制通道；但**不需要** UIA 语义节点也能发信。导航级 PostMessage 点击在稳定态同样可用（目标 rect 来自 OCR 而非 UIA）。

### 23.3 操作教训（重复手机登录）

- 每轮探针**新 launch 隐藏微信 → 登录 → 查完即杀** ⇒ 每轮都向手机推登录确认，用户被迫重复登录 4 次。这是迭代方式的成本，非用户操作问题。
- 修正方向：隐藏实例**登录后保活不杀**，后续只做「附着 inspection」反复查同一已登录窗，用户最多再确认一次。尚未实施（待用户确认方向）。

## 24. 隐藏桌面全屏截图 + agent 自纠错截图接口（E14，`hidden_capture.py` + `experiment_hidden_fullscreen.py`，权威 run `20261119T141758Z`）

### 24.1 需求与方法

- 需求：开发阶段不止 OCR，还要截**隐藏（虚拟）桌面整屏**；使用阶段提供整屏截图接口，供 agent 视觉自纠错。
- 隐藏桌面**非活动输入桌面**、无 DWM 合成屏幕表面 ⇒ 整屏 `GetDC(NULL)+BitBlt` 预计黑屏（实测证实，见下）。可靠兜底=**按窗口矩形把各顶层窗 PrintWindow 拼成整屏 canvas**。两法均在隐藏桌面 worker 线程执行（同桌面），只读。
- 靶=benign `native_test_app` 双窗（**非微信，免手机登录**），PNG 无隐私可保留供读图验证。

### 24.2 实测结果（run `20261119T141758Z`，虚拟屏 5760×2000 多显示器）

| 方法 | bitblt_return / window_count | nonblack_ratio | distinct_colors | 结论 |
|---|---|---|---|---|
| A 整屏 BitBlt | false | 0.0 | 1 | **黑屏，失败**（非活动桌面无合成表面） |
| B 窗口拼接 | 2 窗 printwindow/blit 全 true | 0.0115 | 33 | **整屏重建成功** |

- 拼接图两窗按真实相对位置完整渲染（标题栏/Run action/输入框/Enable option/状态文字清晰可读）；背景黑（隐藏桌面无壁纸）。本会话直接 Read 该 PNG 看清场景 ⇒ **agent 读图自纠错可行**。
- 主机零干扰：`host_foreground_changed=false`、`host_cursor_displacement=0`；`closedesktop_ok=true`、靶进程终止无孤儿。单窗参照 `_capture_feasibility` 亦 `capture_ok=true`。

### 24.3 使用阶段接口

- `hidden_capture.screenshot_hidden_desktop(worker, out_path)` → stitch 整屏 PNG + 虚拟屏几何 + 各窗 rect；只读、不改主机前台/光标。`capture_full(worker,out_dir)` 同时返回 A/B 两法供对照。
- 保留/隐私由**调用方**决定：benign 靶可保留；真实应用（微信等含私聊/联系人）须 hash-then-delete 或 redact 后再持久化。
- 边界：拼接 z-order 按面积近似（大窗先画）、非真实 z-order；背景黑；**不修改冻结 Channel enum**；尚未接入冻结引擎/MCP 契约（使用阶段集成属契约改动，需双人 approve）。

## 25. 隐藏桌面零干扰发信实测成立（E15/E15a，推翻 §19–§23「零干扰发不可行」；`experiment_wechat_hidden_send.py` 权威 run `20261119T144838Z` / 弱验证弃用 `144554Z` / 登录超时 `144034Z`；`experiment_selfdrawn_hidden.py` run `20261119T144530Z`）

### 25.1 起因与自我纠错

- 用户质疑：「OCR 能定位隐藏聊天的输入框/发送键坐标，那你做发信测试了吗？都能截屏了为什么不可靠？你在找什么借口」。此前 §19–§23 的「零干扰发信不可行」是**未实测推断**：只测过登录 Qt 按钮的 PostMessage（E13b），从未对**聊天渲染面/输入框/发送键**做过 PostMessage 发信实验，就把「PostMessage 对自绘不可靠」当定论。**实测优于假设**：该推断错误。
- E15a 先证 PostMessage 鼠标能驱动隐藏桌面自绘面：`selfdrawn_app`（GDI 自绘按钮、无子控件）隐藏桌面起，PostMessage `WM_LBUTTONDOWN/UP` 客户区坐标 (68,95) → 标题 `clicked=1`（`mouse_click_registered=true`）；`WM_PASTE`/`WM_CHAR` 对该无处理器的自绘窗无效（`text_messages_effect=false`，符合预期）。主机前台不变、`closedesktop_ok=true`。⇒ 推翻「PostMessage 对自绘一律不可靠」的笼统说法。

### 25.2 E15 测通的零干扰发信通道（权威 run `20261119T144838Z`）

隐藏桌面 + 第二账户登录（免扫码 auto-enter，主机零干扰）后，对**Qt 主窗 hwnd**（非渲染子窗）PostMessage：

| 步骤 | 通道 | 目标 hwnd | 结果 |
|---|---|---|---|
| 定位输入框/发送键/会话行 | worker PrintWindow → OCR（窗口局部 bounds + 窗原点 → 屏幕 rect） | — | 文件传输助手行 rect `[875,436,985,461]`、标题门控通过 |
| 打开目标会话 | PostMessage 坐标点击会话行 | 主窗 | `title_verified=true` |
| 注入文本 | `WM_CHAR`(0x0102) 逐字符 | **主窗 5377550** | OCR 复核输入框带（y>0.7h）暂存=true |
| 注入对照 | `WM_PASTE`(0x0302) / `WM_CHAR`→渲染子窗 | 渲染 13045368 / 主窗 | 全 false（仅 WM_CHAR→主窗 成功） |
| 发送对照① | PostMessage 坐标点「发送」 | 渲染子窗 13045368 | `bubble_in_message_area=true` 但 `composer_empty=false` ⇒ **未发**（输入框没清） |
| 发送② | PostMessage 坐标点「发送」 | **主窗 5377550** | `bubble_in_message_area=true` **且** `composer_empty=true` ⇒ **真发出** |

- **无漏洞验证**：发送成功判据 = 消息区出现气泡（bounds[3]<0.7h）**且输入框清空**（y>0.7h 无该文本）。仅「任意位置出现文本」会被输入框残留/历史气泡假阳性污染（144554Z 弱验证已弃用）。输入框清空是发送的决断信号（微信仅在发送成功时清 composer）。
- **主机零干扰**：`host_foreground_changed=false`（前台 921150 全程不变）、光标不动；不需要 SendInput、不需要 SwitchDesktop、不碰主机会话。
- **机制定论**：微信 4.x Qt **主窗** hwnd 把 `WM_CHAR` 与鼠标消息路由到聊天 widgets；渲染子窗 `MMUIRenderSubWindowHW` 不接收这些消息（点击/注入均无效）。故零干扰写通道 = **OCR 定位 + 对主窗 PostMessage**，与「渲染面 UIA 零节点」不矛盾（不需要 UIA 语义）。

### 25.3 边界与清理

- 目标仅**文件传输助手**（benign 自传输），标题门控防误发；发送前文本由用户授权（本次质疑即授权该受控发信测试）。**未来每次发信仍须逐次授权**；高影响写操作默认手动审批（原则 7）。
- 隐私：OCR boxes 仅内存；持久化仅 benign 标签/rect/布尔；可读 PNG repo 外 OCR 后即删；私聊/联系人文本不入库。
- 清理核实：桩进程 `stub_alive=false`、`survivors_after=[]`、主机微信树完整（31388+子进程 33944/34276/34352/34436）。**`closedesktop_ok=false`**（E15 三 run 均 false，E14/E15a 为 true）：桩已杀、无孤儿，进程退出即释放桌面句柄，但 CloseDesktop 调用本身返回 false 的原因待查（疑 worker/OCR 线程仍持桌面引用）；不影响主机安全。
- **契约影响**：本通道使 wechat×send_message 可声明**零干扰**（risk none，实测），取代 §20 前台 PHYSICAL_INPUT 提案为更优路线；但 Channel enum 与 capabilities.draft.yaml **仍冻结**，新增 hidden_desktop 写通道属契约数据变更，须提案 + **双人 approve**，未单方放行。正式适配器/引擎/MCP 接入留 G1 门 + B 裁决。
- **完成度**：E15 为**探针实测 verified**（非适配器代码路径）；`packages/adapters/wechat/` 现有适配器走前台 OCR+剪贴板，**尚未**实现本隐藏桌面 PostMessage 通道，不得把探针 verified 冒充适配器 live verified。

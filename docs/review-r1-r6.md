# B 线裁决记录：R1–R6 与 Phase 1 事实核对

针对 `origin/feat/a-perception` @ `ea71495`（2026-11-17 拉取）；裁决对象是该分支
`docs/architecture/guibridge-design.md` §11.5 的 R1–R6 与 §11.2 的十三条核对项。

状态：**B 线会话单方意见，未经双人 approve**。按 D7，新契约冻结前不接入冻结模块；本文件只是将裁决与证据缺口落成可追溯记录。
引用格式 `分支:文件:行` 的分支均为 `origin/feat/a-perception`，行号以 `ea71495` 为准。

---

## 1. 对范围重划的立场

`team-plan.md:30` 把现有 S1–S5 定位为「预研原型资产，不作为参赛交付基线」，`team-plan.md:71` 将 G1 挪到 11/22，
`team-plan.md:85-93` 重写了 B 线职责。

- **接受**：Phase 0–3 作为交付主线；B 线新增职责（FocusGuard 结果整合、Trae 接口文档形式化、研究文档复核、
  依赖许可证审计、交付材料）认领。
- **保留条件 1**：`docs/dev-status.md` 的「fixture 证据 ≠ live 证据」口径与逐阶段未达成项不得被覆盖。
  降级为预研资产改变的是*交付基线归属*，不改变*哪些结论有实测支撑*这一事实。
- **保留条件 2**：B 线四个阶段提交（`c72f5b8`…`b179be5`）仍是 Phase 2 的运行载体——`engine` / MCP 工具面 /
  事件存储 / Dashboard 是被接入方，不是被替换方。`team-plan.md:32`「Phase 1 冻结 engine/MCP/Dashboard」
  与这条一致，Phase 2 接入需保留这些模块的对外契约。

---

## 2. R1–R6 裁决

| # | 裁决 | 理由要点 |
|---|---|---|
| R1 契约冻结范围 | **(b)** 先冻 Router + FocusGuard + 四态分类 | 重试/影响门/桥接尚无冻结侧调用方，先冻会在 Phase 2 里被迫改冻结面 |
| R2 MCP 信封 | **(a)** 扩 `api.md` 增 `state`/`risk`/`interference_observed` | 选 (b) 时 `UNCONFIRMED` 在对外边界塌成失败，原则 6 的可见性丢失，而审计面正是 B 线职责 |
| R3 外部输入归因 | **(a)**，并追加一条：测量缺口 `None` 也降级 | 「没测到」不等于「没干扰」；与我侧未知 verification 名一律 `verified=False` 同纪律 |
| R4 操作命名 | **(a)** 以冻结 `TOOL_SPECS` 名为准，能力表键改名对齐 | 长期供着第二套命名会漂；`operation_names.py` 的漂移守护可留作迁移期工具 |
| R5 send_task live 测量 | **未授权**，本会话未获得用户对新 live 写的批准 | 仪器默认拒绝（退出码 3）这点做得对；R5 是用户决定而非 B 线决定 |
| R6 OCR 路由语义 | **(a)** 路由层对写操作硬排除 `OCR_VISION` | 数据纪律挡不住后来者往表里加条目，原则 3 应是路由不变量 |

### R2 的具体意见（涉及冻结文件 #5）

采纳他们拟议的增量形状（追加字段、不动 `success`/`verified`/`error_code`/`evidence`），但要求三条：

1. `state` 取值集合与四态枚举一一对应，禁止再引入第五个词；文档写明 `unconfirmed` 不是「失败」的同义词。
2. `risk` 必须来自实测能力表，`unknown` 与缺失字段都不得渲染成 `none`（与我侧 `tests/test_actions.py` 的
   「未知 verification 名一律 `verified=False`」同构）。
3. `before/after_snapshot_id` 由 store 注入这条走 B 线：现有 `packages/execution/actions.py:98` 已把快照摘要复制进
   `action` 事件（S4-b 决策 7），Phase 2 落库时**沿用副本方案**，不新增 `GET /snapshots/{id}`，避免二次扩 REST 面。

### R3 的追加条件

`attribution.classify_with_attribution` 把「缺测量证据（`None`）」留作待裁决：本记录裁为**降级**。
理由：`external_input_during_window=None` 表示采样失败，与 `False`（确有采样且无事件）不是同一事实；
把采样失败当清洁窗口，等于让「没看」等价于「看过且干净」。

### R4 的执行边界

改名只动能力表键，不动 `TOOL_SPECS`、不动 `Engine` 方法名（后者是我这条线的冻结面）。
`packages/routing/operation_names.py` 作为过渡期的双向断言保留一个阶段，能力表与规格一致后退役。

---

## 3. §11.2 十三条核对项：逐条意见

`guibridge-design.md:262-276` 共 13 个复选框，下表把同类合并为 10 行；其中「开放问题 5」与「11.4 集成就绪性差异」
两行的裁决分别见第 2 节 R3 与 R2/R4，此处不重复。结论：**13 项原则上全部同意，其中 4 项带附加条件**；
下面两条「保留意见」针对的是 §11.2 复选框**没有覆盖到**的事实缺口。

| §11.2 核对项 | 意见 |
|---|---|
| UIA 风险按「应用×操作×控件×前后台」实测，靶应用记 `FOCUS_SWITCH`，不接受 `LOGICAL_ONLY` 默认 | 同意，E1b 9/9 焦点切换证据充分 |
| E1c 前台起步仍有瞬时切换，事件钩子为 FocusGuard 必备信号 | 同意（run `20261117T090104Z`：钩子补到轮询漏掉的 3 次） |
| 四态语义与「非幂等未确认禁自动重试」 | 同意 |
| `external_input_during_window` 不单独判干扰；污染运行弃用并保留原文件 | 同意 |
| E2 停留曲线仅覆盖 57–138 ms，不外推 | 同意，且 `<50 ms` 未量化必须留在 benchmark 口径里 |
| Trae 主通道 `APP_PROTOCOL`，live 证据仅限一次授权 Chat，agent 模式默认手动审批 | 同意（F9/F10 支撑） |
| 微信负例作为「不支持后台语义操作」证据 | 同意 |
| 能力表逐条实测风险 + `send_task` 仍 `unknown` + 认领授权 live 测量 | 同意「仍 unknown」；**认领 R5 我不能代用户认领**，见上表 |
| 新契约冻结前不接入冻结模块，双人 approve 留痕 | 同意，本文件即留痕 |
| 原则 6 / 原则 7 由 `decide_retry` 与路由审批门强制，与冻结 `SafetyGate` 叠加 | 同意叠加语义；接入时须核对不与 `packages/execution/safety.py::is_high_impact` 判定重复放行 |

### 保留意见 1：`awaiting_approval` 的文本词表没有实测依据

`packages/adapters/trae/states.py:6` 引入

```python
APPROVAL_HINTS = ("等待审批", "需要审批", "需审批", "approval required")
```

并把文件头写成 "Signals verified on 3.6.13 (PROBE_REPORT F6)"（`states.py:1`）。核对本方证据：

- F6 实测的是「CDP 输入→点发送→出现『思考中』→读回 `OK`」，**不含任何审批提示文本**（`src/probe/PROBE_REPORT.md:18`）。
- 未验证项 3「手动审批模式下待审批信号的 DOM 特征」在该分支仍是未验证（`src/probe/PROBE_REPORT.md:54`）。
- 全库搜索该分支，四个词表字符串只出现在 `states.py` 与其单测，没有任何探针输出或 run JSON 支撑。

因此这是一组**推断词表**，不是实测签名。本分支的实现刻意留空
（`packages/adapters/trae/states.py:9` 的 `AWAITING_APPROVAL_MARKERS = ()`，理由见 `docs/security.md`「尚未落实」2）。

请求二选一，不要并行存在两套：

- (a) 词表清空，`awaiting_approval` 仅由 `approval_prompt_visible=True` 这一显式标志驱动（`states.py:15` 的
  `visible` 分支），DOM 签名待实测后回写 PROBE_REPORT 再补文本；
- (b) 保留词表但在代码与 PROBE_REPORT 增补节里标注为 `unverified:*`（同 F10 对审批模式触发器的处理方式），
  且单测名与文档不得称其「已验证」。

补充风险（不影响上面二选一，但 Phase 2 必须知道）：词表是**对不可信回复文本做子串匹配**。
方向是保守的（宁可判 `awaiting_approval` 也不判 `claimed_done`），这点认可；
副作用是模型只要在任何回复里写出「需要审批」四个字，状态机就永久停在审批态、编排侧空等。
建议 `detect_state` 只匹配固定容器内的文本（如审批卡片），不做全文 `in`。

处理进展见 §7：只读探针测不到「审批菜单点得开吗」，本方已把这一段改成显式结论而非静默跳过；
上面 (a)/(b) 二选一针对的是 A 线自己那份 `states.py`，仍待 A 线回复。

### 保留意见 2：能力表新增条目与 R4 的顺序

A 线在 `guibridge-design.md:286` 记录了 OCR 仅定位实测 `none`，并明确「新增表条目涉及
R4 操作名 crosswalk，留 B 线裁决」。
裁决即 R4 (a)：**先定名再进表**。`tests/test_capability_table_integrity.py` 的证据必填守护应当在条目入表前生效，
避免出现「键名待定 → 风险已定级」的中间态。

---

## 4. 合并预案（G1 前必须处理）

### 4.1 `packages/mcp/` → `packages/mcp_gateway/` 的连锁改动

改名方向 B 线**支持**：它正面解决了 `docs/dev-status.md:48-51` 记录的「与官方 SDK 抢顶层名」问题。
本分支需要跟着改的引用点（`b179be5` 实况）：

| 位置 | 现在 | 改名后 |
|---|---|---|
| `tests/test_mcp_tools.py:11` | `from mcp.server import TOOL_SPECS, build_server` | `from mcp_gateway.server import …` |
| `apps/desktop-agent/main.py:186` | `from mcp.server import serve`（靠 `__init__.py` 的 `__path__` 兜底拿到 SDK 符号） | 直接 `from mcp.server import serve` 走真 SDK，不再需要兜底 |
| `packages/mcp/__init__.py`（meta-path finder） | 按名字分派本项目与 SDK | **整文件删除** |
| `apps/desktop-agent/main.py:15`、`registry.py:10`、`examples/handoff_demo.py:29` | `packages` 必须排在 `sys.path` 之前 | 顺序约束解除，可保留但不再关键 |
| `tests/test_live_trae.py:67`、`test_live_handoff.py:78` | stdio 客户端必须在没有 `packages` 的进程里跑 | 该规避可去掉，live 用例结构可简化 |
| `README.md:89`、`docs/architecture.md:26`、`docs/framework.md:26`、`docs/dev-prompts.md:43`、`docs/dev-status.md:23` | 写作 `packages/mcp/server.py` | 统一为 `packages/mcp_gateway/server.py`；契约冻结清单 #2 的**路径**变更也需双人 approve |

### 4.2 双方都改过的文件（冲突面）

`packages/adapters/trae/{adapter,states}.py`、`packages/events/store.py`、`packages/execution/{actions,safety,verifier}.py`、
`apps/desktop-agent/{main,launch}.py`、`examples/handoff_demo.py`、`examples/demo-app/*`、
`README.md`、`docs/{PRD,architecture,security,benchmark,framework,dev-prompts,team-plan}.md`。

约定：**代码冲突以「谁的判据」裁决，不以 diff 行数裁决**；
文档冲突按 §1 保留条件处理（B 线的 dev-status 实况与未达成项不得被覆盖）。
`docs/dev-status.md` 目前只存在于本分支，建议作为 B 线所有权文件保留。

### 4.3 版本基线

三个号码互不一致：exe 元数据 ProductVersion **3.4.20**（FileVersion 2.3.103559）、A 线只读探针
（run `20261117T135355Z`）回报的 UA **`Trae/1.107.1`**、`packages/adapters/trae/locators.yaml:3` 与
F 系列结论基线 **3.6.13**。同一次只读探针另一条更重要的事实：**控件都在、没有改名，会话模式能读出 `Chat`**。

据此本方改变口径：**不再拿版本号当核基线的判据**，改以注册表链的实际命中为准——`semantic_id` 每次动作前
重定位，整条链落空即 `locator_missing` 并停止，命中等价于「这份注册表对该实例可用」；版本号降级为事件里的
环境标注。README「已知限制」里那条已按此改写（只留一处，原来重复了两遍）。

代码实况与此一致，不是新决定：`app_version` 只从 `locators.yaml` 的标签流进 `Engine`/`save_locator`
（`apps/desktop-agent/main.py:53`），运行期没有任何一处拿它与真实实例比对——重定位只认链上策略能否命中 DOM。
副作用请一并评审：heal_patches 以 `(semantic_id, app, app_version)` 为主键，真人批准的补丁会挂在
「3.6.13」这个标签上，与真实实例的版本号无关；若 A 线要按版本分节，`locators.yaml` 与
`locator_cache.load(app, app_version)`（S1 骨架）都需一起定口径。

请 A 线在 §11.2 回复里补两项：探针实例是托管启动还是接管已启动进程；UA 与 ProductVersion 取自哪个通道。
若 Phase 1 的实测确实跑在 3.4.20/1.107.1，`locators.yaml` 需新开分节——那是冻结文件 #3，走双人 approve。

---

## 5. Phase 2 的 B 线交付条目（认领）

1. Router/FocusGuard/四态分类接入 `apps/desktop-agent/engine.py` 与 MCP 工具面（依赖 R1、R2 冻结）。
2. `capabilities.draft.yaml` → 正式能力表的 Trae 条目形式化，与 `locators.yaml` 的 `app_version` 对齐。
3. `packages/execution/verifier.py` 与 `decide_retry` 的边界文档化：验证器只认 git 与退出码，重试策略只认幂等标注，
   两者不得互相覆盖。
4. 竞品分析 / 原创性日志复核定稿 + 依赖许可证审计（`team-plan.md:92-93`）。
5. 交付材料（站点/录屏）——依赖真实通道与用户对外发布授权，未获授权前不产出。

## 6. 未决项

- **R5 需要用户明确授权**：是否允许一次 Chat 模式固定无害消息以实测 `send_task` 的焦点风险。
  现有「全部授权」不自动延伸，本记录不代答。
- `api.md` 扩展（R2a）与契约冻结清单 #2 的路径变更均需双人 PR，非本文件可生效。
- `EventStore.prune()` 接线点仍是产品决定（`docs/security.md`「尚未落实」1）。

---

## 7. 执行记录（2026-11-17，A 线只读探针之后）

A 线步骤 1（只读：控件在不在、有没有改名、当前是什么模式）已完成，对方报告该分支 309 测试全过。
结论两条：**控件都在且未改名，模式态能读出 `Chat`**（本方担心的「改名」在本机不存在）；
**审批菜单能否打开没测**——那要点击，超出只读范围。双方同意这是 B 线步骤 2，本方已落地：

| 改动 | 位置 | 效果 |
|---|---|---|
| 审批模式读取从静默 `return` 改为显式结论 | `packages/adapters/trae/adapter.py::force_manual_approval` | 必落一种 `outcome`，每次都写 `approval_mode_read` 事件 |
| 肯定证据替代「缺席即通过」 | `packages/adapters/trae/states.py::approval_state`、`approval_mode_manual` 谓词 | 读出「手动审批」标签才算手动；只命中 class 记 `unreadable`，都读不到记 `absent`，批准后仍读到 `auto` 记 `manual_label_unreadable` |
| agent 模式加硬门 | `packages/adapters/trae/adapter.py::send_task` | 除 token 外还必须读出 `manual_confirmed`，F9 那类误点击不能再悄悄跑在 auto 下 |
| 已手动时一次点击都不发 | 同上 | 不产生审批请求（断言 `list_approvals() == []`），少做一遍高影响动作 |
| 标签可测性交给 A 线 | `locators.yaml`（冻结 #3） | 本方不碰注册表；菜单开合的实测见下 |
| 替身行为与判据对齐 | `apps/desktop-agent/simulated.py` | G1 换真实通道前，模拟通道按同一套标签规则应答（非冻结文件） |

证据等级：**fixture**。`tests/test_adapter_flow.py` 新增 6 条——已手动不发点击、读不到触发器仍记录并继续、
标签不可读说 `unreadable`、批准后仍读不到手动 → `approval_required` 且任务 `failed`、批准后两个标签同时命中
（复读不是 `manual`）同样致命、agent 拒绝未确认——全套 `181 passed, 5 deselected`。
**真实 Trae 上的标签读取与菜单开合仍未测**：那需要一次带点击的 live 运行，排在 G1 或下面的 R5 之后。

R5 状态不变：本方未获用户对新 live 写的授权，不代答；A 线仪器默认拒绝（退出码 3）这点做得对。

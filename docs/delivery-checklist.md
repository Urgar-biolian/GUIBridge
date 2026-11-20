# 交付收尾清单（A 线视角，2026-11-20）

把「还差什么才能算完成」落成可执行清单。门与日期以 `README.md` / `docs/handoff-a-to-b.md` §5 为准
（G1 11/20 → G2–G4 11/23–27 → G5 11/30）；`docs/team-plan.md` §4 仍是旧日期（G1 11/22 / G3 11/30），
属文档不一致，待与 B 一起对齐，本文不擅自改对方的进度表。

## 1. 门状态

| 门 | 状态 | 卡在哪 |
|---|---|---|
| G1（11/20） | **未过**：A 侧就绪（`65a5b23`）；B 侧远端与报告不一致，见 §7 | B 推的是 `feat/b-control-plane`（`b25aa3e..2d130af`，8 提交），**远端没有 `integrate/g1`，`9804c69` 不存在**；且 B 分支基于旧 main、不含 A 线任何工作 |
| G2–G4（11/23–27） | 未开始 | 需 B 补控制面 live 通道（`perception.cdp.CDPChannel` → `adapters.base.Channel`）+ 默认替换的双人 approve + 用户逐次 live 授权 |
| G5（11/30） | 未开始 | 前置 G1–G4 live 全通；站点/录屏对外可见需用户确认；许可证已定 MIT（2026-11-20） |

## 2. 不越门、现在就能做（A 线）

- [x] 依赖许可证审计 + 提交/泄露检查 → `docs/research/license-audit.md`、`tools/license_audit.py`（commit `a3b5736`）
- [ ] **bench 的 live A/B/C 组**：`tests/bench/bench.py` 目前只有 `mode=fixture-simulation`，没有真实通道组；
      要填 benchmark.md 的 live 空格子，必须先加一组走真实适配器的对照（属代码工作，**跑之前仍需授权**）
- [ ] **live 测试钉窗**（handoff §4）：`tests/test_live_heal.py` / `test_live_locate.py` 取首个 CDP 页（`trae[0]`），
      demo 窗口开着会误指向 demo；应按目标窗口标题钉住
- [ ] team-plan 日期与 README/handoff 对齐（与 B 协商后改）
- [ ] 录屏分镜定稿（§4 草案）

## 3. Phase 2 live 运行清单（每项默认拒绝，授权按指定范围生效）

| # | 项 | 命令 | 授权门 | 已有证据 | 判据 |
|---|---|---|---|---|---|
| 1 | 非 live 回归 | `python -X utf8 -m pytest -q` | 无需 | 375 passed / 1 skipped（2026-11-20 本机） | 全绿 |
| 2 | live 定位/自修复/MCP（4 条） | `GUIBRIDGE_LIVE=1 python -X utf8 -m pytest -m live -q` | 只读 + 固定无害 chat 消息（既有授权范围内） | S2 闭环、S1/S4 定位 | 4/4；需真实 Trae + 9222，demo 窗口关掉或先钉窗 |
| 3 | send_task 发送点击风险复测 | `python -X utf8 src/probe/verify_trae_send_focus.py --authorize-live-write --project-path <隔离 demo>` | **每次都要新授权**；无 flag 时不连接、不发送、exit 3 | run `20261118T044436Z`/`044518Z` → 发送点击 **none**，能力表已 frozen | 结论已成立，**不必重跑**；只为录屏需要时才跑 |
| 4 | 窗口移动后重复 send_task ≥3 | **尚无现成探针**（`verify_trae_send_focus.py` 只测一次发送） | 需新授权 + 先写探针 | 无 | ≥3 次发送、每次 FocusGuard 包裹、工作区零变更 |
| 5 | agent 隔离 demo 改码 | `python -X utf8 examples/agent_live_demo.py --authorize-live-agent --project-path D:\QoderTest\guibridge-demo-workspace` | 仅隔离 demo + 人工手动审批；真实项目 basename 硬阻断 | run `20261118T074629Z`，task `task_69f57b6a5f03`，submitted→verified | 独立 Verifier 通过（仅改 index.html + `node --test` 3/3） |
| 6 | 微信负例（OCR 仅定位） | `python -X utf8 src/probe/gbdash.py`（127.0.0.1:8710）快照/实时画面 | 只读；微信快照与实时画面均需 confirm；**发信需逐次授权** | E10/E13/E15 | 不发送即无需新授权；私聊内容脱敏 |
| 7 | 控制面端到端（MCP 网关 + Dashboard + 审批 REST + SSE + heal-review） | `python apps/desktop-agent/main.py --mode live` | **当前自拒启动**（CDPChannel 未包成 Channel） | 无 | 需 B 补通道 + 双人 approve 后才谈授权 |

## 4. 录屏分镜（草案，待用户确认）

| 镜头 | 内容 | 素材来源 | 是否需 live 写 |
|---|---|---|---|
| 1 | 问题：纯坐标回放在窗口移动/缩放后误点击 | bench 原始 JSON（A 组 9 次误点击） | 否（fixture） |
| 2 | 语义定位 + 后置状态验证拒绝不可操作目标 | live 只读定位 / fixture C 组 | 否 |
| 3 | 零干扰后台：隐藏桌面第二 Trae 实例，主机前台不变 | `gbmirror` 镜像窗口 | 否（只读观测） |
| 4 | web 观测：会话/能力表/FocusGuard 事件流 + 实时镜像 | `gbdash` 127.0.0.1:8710 | 否（录屏用 Trae 会话，避开私聊） |
| 5 | 安全门：高影响无令牌 → `no_executable_channel`；审批提示不执行；「完全访问」触达 DOM 前被拒 | 单测 + 只读演示 | 否 |
| 6 | 真实 agent 在隔离 demo 改码 + 独立 Verifier | 重跑 #5 或复用已有 run 证据 | **是**（仅隔离 demo） |
| 7 | 如实标注：fixture 与 live 两栏分开，未达标项显式说明 | benchmark.md / 本文 | 否 |

录制工具：隐藏桌面内容用 `gbmirror` 硬件 H.264（镜像窗口左侧列表**最后一行**点击开始/停止，
输出 `var/experiments/gbmirror_rec.mp4`，gitignored）；主机侧镜像窗口/浏览器另用主机录屏。
产物不入库；发布前脱敏本机路径、用户名、私聊文本。

## 5. 提交检查

已完成（`a3b5736` + MIT 声明）：许可证审计（57 Python / 24 crate / 50 npm 全宽松，两处 MPL-2.0 文件级弱 copyleft）、
**本项目选定 MIT**（`LICENSE` + `pyproject.toml` `license = {text = "MIT"}` + `gbmirror/Cargo.toml` `license = "MIT"`）、
硬编码用户名改走 `APPDATA`、Pillow 补进依赖声明、探针日志移出索引 + `*.log` 忽略、
基准原始记录不再被 ignore 挡住、无凭据/无二进制入库。

待做：
- 干净 venv + 锁文件复跑一次非 live 套件（本机是 conda + 用户 site 混合环境，存在同名多版本 dist-info）
- OCR extra 在干净环境按 `opencv-python` 安装后重跑审计（本机由 headless/用户 site 的 cv2 满足）
- 公开站点不得包含本机执行器、调试端口转发、`var/experiments` 证据目录（handoff §5 G5 前置）

## 6. 需用户决策

1. ~~许可证~~ → **已定 MIT**（2026-11-20），三处声明已落地。
2. **Phase 2 live 授权范围**（仍待定）：
   - 最小范围：只跑 #1/#2/#6 只读项 → 镜头 1–5、7 可拍，镜头 6 复用已有 run 证据；
   - 完整范围：另授权 #4（需先写窗口移动重复发送探针）与 #5 重跑（隔离 demo）→ 镜头 6 重拍、S4 live 验收补齐。

## 7. B 线远端复核（2026-11-20，`git fetch` 后实测）

远端只有三条分支：`feat/a-perception`（`65a5b23`）、`feat/b-control-plane`（`2d130af`）、`main`（`b25aa3e`）。
**没有 `integrate/g1`；`git cat-file -t 9804c69` 返回 not a valid object name。**

B 新推的 8 个提交（`b25aa3e..2d130af`）：`c72f5b8` S2、`a7bb349` S3、`53d66e2` S4-b、`ce9e60a` S5-b、
`b179be5` docs、`7497e55` R1–R6 裁决、`b99babc` fix(adapter)、`2d130af` docs；55 文件 / +6621 −82。

与报告不一致的三点（均可复算）：

1. **F10 弹层修复不在远端**。`git grep permissionModePopover|permissionModeItem|is_allowed_approval_target`
   在 B 全树 **0 命中**；`packages/adapters/trae/states.py` 只有 `approval_state()` 读 trigger 标签
   （manual/auto/unreadable/absent），`locators.yaml` 的 `trae.chat.approval_mode` 链仍只指向 trigger
   （`button[aria-label='自动审批']` / `[class*=permissionModeTrigger]`），没有弹层行选择器。
   即 `b99babc`「把审批模式当证据读」**不等于**报告里「切到手动审批」的修复；F10 根因在远端版本仍存在。
2. **B 分支不含 A 线任何工作**。`merge-base(A,B) = b25aa3e = main`，`--is-ancestor A B` 为 NO。
   B 树里没有 `routing` / `focusguard` / `integrated` / `routed_executor`，MCP 仍是 `packages/mcp/server.py`
   （A 线已是 `packages/mcp_gateway/server.py`），也没有 `src/probe` 镜像/gbdash 与 research 文档。
3. **合并是真冲突，不是 fast-forward**。相对 main，B 改了 `packages/execution/actions.py`、
   `packages/execution/safety.py`（handoff §2.5 六条勿动路径中的两条），A 也改了这两条 + `docs/api.md` + MCP 路径；
   两边还都改了 `pyproject.toml`（B 加 `httpx>=0.27` 到 dev extra，A 加 `pillow>=10.0` 到 dependencies，这两处可自动合并）。
   B 的 `docs/` 是另一套文件名（`architecture.md` / `review-r1-r6.md` / `dev-status.md`），与 A 的
   `architecture/guibridge-design.md` / `research/*` 并存，需要人工决定归并方式。

结论：**G1 未过**。需要 B 确认到底推了什么（报告中的 `9804c69`/`integrate/g1` 与远端不符），
并把分支接到最新 A 线、解决 `packages/mcp` vs `packages/mcp_gateway` 的结构分歧与两条 execution 冻结文件的冲突，
再按六条勿动路径 + 非默认接线复核。A 线不擅自合并、不改对方分支、不替换默认路径。
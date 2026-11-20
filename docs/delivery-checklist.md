# 交付收尾清单（A 线视角，2026-11-20）

把「还差什么才能算完成」落成可执行清单。门与日期以 `README.md` / `docs/handoff-a-to-b.md` §5 为准
（G1 11/20 → G2–G4 11/23–27 → G5 11/30）；`docs/team-plan.md` §4 仍是旧日期（G1 11/22 / G3 11/30），
属文档不一致，待与 B 一起对齐，本文不擅自改对方的进度表。

## 1. 门状态

| 门 | 状态 | 卡在哪 |
|---|---|---|
| G1（11/20） | A 侧就绪，已推送至 `a3b5736` | B 的 `integrate/g1` + `9804c69` **不在本机仓库**，无法代码级复核；等 B 接到最新 A 线后推，再按六条勿动路径 + 非默认接线复核 |
| G2–G4（11/23–27） | 未开始 | 需 B 补控制面 live 通道（`perception.cdp.CDPChannel` → `adapters.base.Channel`）+ 默认替换的双人 approve + 用户逐次 live 授权 |
| G5（11/30） | 未开始 | 前置 G1–G4 live 全通；站点/录屏对外可见需用户确认；**本项目许可证尚未选定** |

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

已完成（`a3b5736`）：许可证审计（57 Python / 24 crate / 50 npm 全宽松，两处 MPL-2.0 文件级弱 copyleft）、
硬编码用户名改走 `APPDATA`、Pillow 补进依赖声明、探针日志移出索引 + `*.log` 忽略、
基准原始记录不再被 ignore 挡住、无凭据/无二进制入库。

待做：
- **本项目许可证未选定**（无 LICENSE 文件、`pyproject.toml` 无 license 字段、`gbmirror/Cargo.toml` 无 license）——用户决策
- 干净 venv + 锁文件复跑一次非 live 套件（本机是 conda + 用户 site 混合环境，存在同名多版本 dist-info）
- OCR extra 在干净环境按 `opencv-python` 安装后重跑审计（本机由 headless/用户 site 的 cv2 满足）
- 公开站点不得包含本机执行器、调试端口转发、`var/experiments` 证据目录（handoff §5 G5 前置）

## 6. 需用户决策（两项）

1. **许可证**：参赛交付用 MIT / Apache-2.0 / 其他 / 仅提交评审不开源。定了就加 LICENSE + pyproject/Cargo 字段。
2. **Phase 2 live 授权范围**：
   - 最小范围：只跑 #1/#2/#6 只读项 → 镜头 1–5、7 可拍，镜头 6 复用已有 run 证据；
   - 完整范围：另授权 #4（需先写窗口移动重复发送探针）与 #5 重跑（隔离 demo）→ 镜头 6 重拍、S4 live 验收补齐。
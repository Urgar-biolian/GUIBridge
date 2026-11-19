# 架构设计

详见 [PRD.md](PRD.md) §4。本文补充模块边界与关键决策。

## 模块边界

- `perception/*`：只产出带通道证据的原始元素 dict，不做业务判断。CDP 为主通道（Electron），UIA 覆盖原生应用，OCR 补盲，vision 为 P2。
- `semantic/*`：融合结果 → GUIElement；semantic_id 注册表与实时重定位。坐标永不跨执行复用。
- `execution/*`：动作执行（前后快照+后置验证）、安全门、独立验证器。verified 只由 verifier 授予。
- `adapters/*`：业务状态机与通道能力探针；YAML 注册表按 app_version 分节。
- `events/*`：SQLite 审计；所有 MCP 调用与状态迁移留痕。
- `mcp_gateway/server.py`：固定 8 工具；Engine Protocol 注入，工具层不含业务逻辑；同步引擎调用经线程卸载，避免事件循环嵌套。
- `apps/desktop-agent`：托管启动（loopback 随机调试端口）、审批端点、SSE 事件流。
- `apps/dashboard`：Vue3+TS+Vite；任务/迁移时间线、SSE 事件回放、定位器与 heal 补丁审核、一次性审批。
- `tests/bench`：A/B/C 可复现基准（fixture 视口变换与漂移注入）。

## 实现现状（截至 S4-b，2026-11-17）

模块边界是设计意图，这张表是当下事实。`NotImplementedError("Sx")` 是骨架里标的阶段归属，
下面按「谁负责、有没有跑过」重列一遍（详见 [dev-status.md](dev-status.md)）。

| 位置 | 状态 | 归属 |
|---|---|---|
| `packages/adapters/trae/{adapter,states}.py` + `locators.yaml` | 已实现（通道能力探针 + 提交→状态→读回状态机） | B 线 S2 |
| `packages/execution/{actions,safety,verifier}.py` | 已实现（后置条件验证、审批门、独立验证器） | B 线 S2/S3 |
| `packages/events/{schema.sql,store.py}` | 已实现（append-only 事件、审批、注册表、快照、保留期函数） | B 线 S2 |
| `packages/mcp/server.py` | 已实现（固定 8 工具 + 每次调用审计行） | B 线 S2 |
| `apps/desktop-agent/{engine,main,launch,registry}.py` | 已实现（13 端点 REST + SSE + `--mcp` stdio + 托管启动） | B 线 S2 |
| `apps/desktop-agent/simulated.py` | 已实现（`SimulatedTrae` 通道 + `RegistryResolver`，fixture 驱动） | B 线 S2，pre-G1 临时件 |
| `apps/dashboard/` | 已实现（四页：任务/回放/定位器/审批，只读 + 审批写） | B 线 S4-b |
| `packages/perception/{cdp,uia,ocr,fusion}.py` | **仍是 S1 骨架**（`NotImplementedError("S1")`） | A 线 |
| `packages/perception/vision.py` | **P2，不实现** | — |
| `packages/semantic/resolver.py`、`locator_cache.py` | **仍是骨架**：只有协议与 `heal()` 签名，失效检测/唯一候选/漂移补丁生成未实现 | A 线 S4-a |

后果要说白：pre-G1 能跑的只有模拟通道，所以 `apps/desktop-agent/simulated.py` 里的 `RegistryResolver`
顶的是 `packages/adapters/base.py::ElementResolver` 协议；等 A 线的真实重定位落地，替换的是这个实现位置，
`execution/actions.py` 与 Dashboard 不需要改。

## 一次任务的真实数据路径

```text
规划侧 Agent ──(MCP stdio: trae.send_task)──► ControlPlane(engine.py)
                                                  │  同一进程也可由 REST POST /tasks 进入
                                                  ▼
                        TraeAdapter ──► Executor.perform ──► SafetyGate（白名单/身份/审批 token）
                                                  │              │缺 token → 写 approval_requested 后停止
                                                  ▼              ▼
                          Channel（pre-G1 为 SimulatedTrae）   EventStore（action / task_state 只追加）
                                                  │
                                    claimed_done ─┘   ← 执行侧自述，永远不等于交付
                                                  │
规划侧 handoff（examples/handoff_demo.py）──► Verifier.verify（git 范围 + 验收命令退出码）
                                                  │
                                    store.set_task_state(..., actor="verifier")  ← 只有这条路径能写 verified
                                                  │
Dashboard（Vue，只读 + 审批）◄── REST /api/* + SSE /api/events ◄──────────────────┘
```

要点：`GET /tasks/{id}` 与 Dashboard 读的是事件存储，不是任何一个进程的内存；
所以另一个进程里的验证器写完 `verified`，界面立刻一致（决策 6）。
同一份 SQLite 可以同时被 REST 平面与 `--mcp` stdio 进程打开（S4-b 的 MCP 调用表就是这么灌进真实调用的），
跨进程一致性同样靠事件存储。

## 关键决策记录

1. **CDP 优先而非 UIA 优先**：实测 Trae 聊天 WebView 在 UIA 中不可见（PROBE_REPORT F1/F2），CDP 提供全语义（F3）。
2. **CLI chat 降级为候选通道**：3.6.13 静默投递失败（F4）；适配器加载时做通道探针。
3. **读回主通道为 CDP DOM**：回复归档扩展需项目绑定且版本重验（F7），作备通道。
4. **固定工具面**：不随识别元素动态生成 MCP 工具，避免 Agent 上下文臃肿。
5. **三态分离**：submitted / claimed_done / verified 严格区分，界面完成不等于交付完成。
6. **状态以事件存储为准，不以进程内存为准**（S4-b）：`verified` 通常由另一个进程写入，
   `ControlPlane.get_status` 早期只回 adapter 的记忆，导致跨进程验证后 HTTP 仍报 `claimed_done`。
   现在 `apps/desktop-agent/engine.py:94` 用 `store.get_task()` 覆盖 state/transitions/evidence。
7. **回放证据复制进事件，而不是扩 REST 面**（S4-b）：`docs/api.md` 冻结且没有「按 id 读快照」的端点，
   前端拿着 `snap_xxx` 无从显示。`packages/execution/actions.py:98` 把
   `{snapshot_id, ts, element_count, image_path}` 摘要写进 `action` 事件——
   sql.md 规定事件与快照只追加不改写，所以这份副本不会和源数据漂移。
8. **Dashboard 不新增控制通道**（S4-b）：没有任务提交入口，全部写操作只有审批授予、窗口白名单、修复补丁审核三种，
   且都走已冻结的 13 个端点。这样「界面能不能改状态」这个问题有明确答案：不能，只有人能批。
9. **审批凭据按一次性能力设计**（S2）：库里只存 SHA-256 摘要，明文只在 loopback 响应里出现一次；
   绑定 `{window_id, semantic_ids, actions}` 范围、默认 600 秒、用过即废（`used` 置 1）。
10. **文件级改动不由 GUI 通道假装完成**（S3/S4-b）：预 G1 通道只改 fixture DOM，
    演示工作区的编辑由 `examples/handoff_demo.py` 用 git 落提交并在文档里标明，
    验证器核对的是变更范围与验收命令，不声称「Trae 真的动了文件」。

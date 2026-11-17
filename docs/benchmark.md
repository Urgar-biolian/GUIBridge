# 基准评测

> **状态：未实测（2026-11-17）。** 下表所有数字格留空不是「还没填」，是「跑不出来」：
> 三个实验组都要求真实 Trae 窗口，而 A 线感知通道（`packages/perception/cdp.py`、`uia.py`、`ocr.py`）
> 仍是 S1 骨架，集成门 G1 未过。以模拟通道（`tests/fixtures/trae/dom_ide_idle.json`）产出的「成功率」
> 衡量的是 fixture 本身，不能当作 GUIBridge 的成绩，因此一条都不写。

实验组：A 纯截图+视觉模型+坐标点击；B CDP/UIA+OCR 语义定位（无状态验证）；C GUIBridge 适配器+状态验证。

场景与重复次数：发送消息、切换模式、读取回复、窗口移动、窗口缩放、主题切换、异常弹窗；每场景 ≥10 次。

| 场景 | 组 | 次数 | 成功 | 成功率 | 误点击 | 模型调用次数 | 失败类型 | 阻塞原因 |
|------|----|------|------|--------|--------|--------------|----------|----------|
| 发送消息 | A/B/C | | | | | | | 需 G1：CDP 通道 + 真实 Trae |
| 切换模式 | A/B/C | | | | | | | 同上；`trae.chat.mode_entry` 的菜单实测在探针 F5/F9 |
| 读取回复 | A/B/C | | | | | | | 同上；回复读回基线是探针 F6 |
| 窗口移动 | A/B/C | | | | | | | 需 G2：跨显示器 DPI 换算（探针 F8 实证漂移） |
| 窗口缩放 | A/B/C | | | | | | | 需 G2 |
| 主题切换 | A/B/C | | | | | | | 未做探针，选择器基线缺失（PROBE_REPORT 未验证项） |
| 异常弹窗 | A/B/C | | | | | | | 需 G1；`awaiting_approval` 至今无实测 DOM 签名（未验证项 3） |

验收目标（受支持场景）：成功率 ≥90%；窗口移动后 ≥90%；高影响控件误点击 0；动作可追溯率 100%。

## 已经具备的、可以直接接上的部分

- **可追溯率这一项已由事件存储保证**：`packages/events/store.py` 对每次动作写 `action` 行
  （含 semantic_id、前后快照摘要、成功/verified、error_code），MCP 侧每次调用写 `mcp_call` 行；
  这一列将来不需要人工统计，`SELECT` 即得。其余三列（成功率/误点击/模型调用次数）没有实现任何自动统计。
- **评测记录的最小 schema 已经在跑**：`docs/sql.md` 的事件行 + `verify` 事件的 payload 足以复现 C 组判定；
  A/B 组要新增的字段（点击坐标、模型调用计数）尚未定表，归 S5-a 与 A 线一起定。
- **C 组的判据不用另写**：`packages/execution/verifier.py`（范围 + 验收命令退出码）就是 C 组的成功定义，
  直接复用可避免「评测脚本自己放宽标准」。

## G1 之后怎么跑

```bash
pytest -m live                                    # 5 条 live 用例，当前默认 deselect
python apps/desktop-agent/main.py --mode live --db ./guibridge.sqlite3 --port 8765
(cd apps/dashboard && npm install && npm run dev) # http://localhost:5173
```

每场景 ≥10 次的循环脚本按 dev-prompts S5 第 1 项落在 `tests/bench/`——**该目录目前不存在**，
归属 README 分工表的 S5-a（A 线评测组）；B 线不另起一套统计口径，等 A 线脚本入库后按上表填数。

纪律：未达标如实记录；原始运行日志与脚本入库（`tests/bench/`）；不以单次成功代表成功率；
没有真实通道时不产数字。

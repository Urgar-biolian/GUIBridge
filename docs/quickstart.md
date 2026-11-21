# 快速开始

四层入口，按目的选一层。所有命令在仓库根目录执行；控制平面只绑定 loopback，不会暴露到网络。

**前置条件**

- Windows 10/11 交互式桌面会话（锁屏 / 安全桌面 / 远程桌面断开不支持，见 [security.md](security.md)）。
- Python ≥ 3.10（实测环境 3.13）。建议虚拟环境隔离依赖。
- Node.js ≥ 18：仅 Dashboard 与交接演示的验收命令需要。
- 可选：Rust 工具链（隐藏桌面原生镜像/录制）；`.[ocr]` extra（OCR 通道）。
- 第 1–3 层**不需要**打开任何真实应用；第 4 层需要真实 Trae 与逐条人工授权。

## 1. 五分钟模拟演示

目标：不打开真实应用，看到「提交 → 声称完成 → 独立验证」整条链与审计记录。

```bash
python -m venv .venv
.venv\Scripts\activate                  # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# 终端 A：控制平面（simulated = fixture 通道）
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --port 8765

# 终端 B：Dashboard（只读展示 + 审批，不能提交任务）
cd apps/dashboard && npm install && npm run dev
# 打开 http://localhost:5173 （/api 已反代到 8765）

# 终端 C：交接演示（规划侧任务包 → 执行侧自称完成 → 独立验证器判定）
python examples/handoff_demo.py --node node
# 可选：--workspace <隔离 git 仓库路径>（缺省用临时目录 guibridge-demo-workspace）
#       --report report.json 保存完整 JSON 报告
```

演示工作区说明：新副本自动播种「改动前」基线（删参考按钮、留验收用例）；模拟模式由演示脚本的
写入代层恢复参考实现——这是**模拟证据**，不代表真实 Trae 改码（那属于第 4 层）。
缺省临时工作区若已存在会原样复用（其 HEAD 即基线）；想从头看完整闭环，传一个新建的 `--workspace` 目录。

**成功判据**

- 终端 C 输出状态序列 `submitted → running → claimed_done → verified`，且 `verified` 来自验证器（Git 变更范围 + 验收命令退出码），不是执行侧自述。
- Dashboard 时间线出现该任务；事件回放可逐条展开；无截图处显式写「无截图」（模拟通道不产截图）。
- 回复文本带 untrusted 标记，只被复制进报告，不会被执行。

不想装 Node/Dashboard 时，只跑终端 A + C 也能看到完整闭环文字报告。
在线交互演示（无需安装）：[公开展示页](https://guibridge-showcase-o66tz0jimfr.qoder.zone)。

## 2. MCP 客户端接入

目标：把冻结的 8 个工具接进任意 stdio MCP 客户端（Agent 侧）。

**推荐入口（官方）**：`packages/mcp` 工具面，MCP SDK 2.x，随 `.[dev]` 安装即可用。

```bash
python apps/desktop-agent/main.py --mode simulated --db ./guibridge.sqlite3 --mcp
```

客户端配置示例（把路径换成你的仓库绝对路径与解释器绝对路径）：

```json
{
  "mcpServers": {
    "guibridge": {
      "command": "/path/to/guibridge/.venv/Scripts/python.exe",
      "args": ["apps/desktop-agent/main.py", "--mode", "simulated", "--db", "./guibridge.sqlite3", "--mcp"],
      "cwd": "/path/to/guibridge"
    }
  }
}
```

**成功判据**：客户端 `tools/list` 返回恰好 8 个工具（`gui.list_windows`、`gui.inspect_window`、`gui.find_element`、`gui.perform_action`、`gui.get_snapshot`、`trae.send_task`、`trae.get_status`、`trae.read_result`）；每次调用在事件存储留下一行 `mcp_call` 审计。

**实验 / 兼容入口**：`packages/mcp_gateway`（SDK 1.x FastMCP 写法）。仅在你必须用 1.x SDK 时单独建环境装 `mcp<2` 后使用；工具名与错误码与官方面一致。`examples/handoff_mcp_demo.py` 走的是这条实验面（需 `mcp<2` + node）。新接入一律推荐官方面。

契约（参数、错误码、REST/SSE）见 [api.md](api.md)；交接语义与提示注入防护见 [agent.md](agent.md)。

## 3. 开发与测试

```bash
python -m pip install -e ".[dev]"
python -m pytest -m "not live"          # 期望：569 passed / 3 skipped / 8 deselected
                                        # 3 skipped = MCP 1.x 网关用例（当前环境为 SDK 2.x）
                                        # 8 deselected = live 用例，默认不跑

# 基准复跑（fixture 模拟 A/B/C 三组；原始 JSON 入 tests/bench/results/）
python -X utf8 tests/bench/bench.py --iterations 10
```

**成功判据**：非 live 全绿；跳过与 deselect 的原因可读（不伪称通过）。基准结论口径见 [benchmark.md](benchmark.md)：策略排序成立，绝对成功率是 fixture 口径。

工程纪律（fixture-first、失败路径必测、不用固定 sleep 判状态、读回文本恒 untrusted、契约冻结双人 approve）见 [CONTRIBUTING.md](../CONTRIBUTING.md) 与 [framework.md](framework.md)。

## 4. 实验性 live 操作

> **警告**：本层会操作真实桌面应用。仅允许 chat 模式、隔离仓库、逐条人工授权；禁止 agent 模式 live。
> 控制平面 `--mode live` 当前拒绝启动（live 通道集成中）；现有 live 证据来自直连适配器路径与受控实验。
> 完整安全边界与「尚未落实」清单见 [security.md](security.md)。

前置：

1. 真实 Trae 以托管方式启动（`apps/desktop-agent/launch.py` 自动分配 loopback-only CDP 端口），或自行以仅 loopback 的调试端口启动；
2. 目标工作区是**隔离 git 仓库**（禁止指向真实项目）；
3. 该 Trae 窗口已由人在 Dashboard 显式加入白名单（测试不代替人做白名单决定）；
4. 审批模式为手动审批；高影响动作需一次性 token。

```bash
# 环境变量逐条授权后才运行；缺任一前提整模块跳过，绝不退回 fixture 伪称 live
GUIBRIDGE_LIVE=1 GUIBRIDGE_LIVE_PROJECT=<隔离仓库路径> python -m pytest -q -m live
```

**成功判据**：任务进入 `claimed_done` 后由独立验证器判定；结束后核对隔离仓库变更范围与验收命令；主机光标与前台窗口零干扰（FocusGuard 采样观察）。

**当前未验证**（不要当成已支持）：Trae 真实改码的 live 端到端、live A/B/C 对照、跨显示器 DPI、锁屏/安全桌面场景。逐条状态见 [dev-status.md](dev-status.md)。
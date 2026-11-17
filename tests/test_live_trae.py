"""S2 出口条件的 live 部分：外部 MCP Client 通过 stdio 驱动一条无害的 chat 消息。

默认被 `-m "not live"` 排除（docs/framework.md 工程纪律）。运行前提：

    GUIBRIDGE_TRAE_EXE   Trae 可执行文件（默认 D:\\Program\\Trae\\Trae.exe）
    GUIBRIDGE_PROJECT    隔离的目标工作区（独立 git 仓库；禁止指向用户真实项目）
    并且该 Trae 窗口已由用户在 Dashboard 上显式加入白名单——测试不代替人做白名单决定。

安全约束来自 PROBE_REPORT F9 与 dev-prompts S2：只允许 chat 模式、审批模式必须手动、0.5s 仅作轮询间隔
而非状态推断、结束后核对目标工作区零文件变更。任一前提缺失则整模块跳过，绝不退回 fixture 数据并声称
live 已验证。
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TASK_TEXT = "请只回复 OK 两个字母，不要执行任何其他操作。"
pytestmark = pytest.mark.live


def trae_exe() -> Path:
    return Path(os.environ.get("GUIBRIDGE_TRAE_EXE", r"D:\Program\Trae\Trae.exe"))


def project_dir() -> Path:
    return Path(os.environ.get("GUIBRIDGE_PROJECT", ""))


def cdp_channel_ready() -> bool:
    """Gate G1: without the A-line channel a live run would prove nothing."""
    from perception.cdp import CDPChannel
    try:
        asyncio.run(CDPChannel(port=0).scan_elements())
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


@pytest.fixture(scope="module")
def live_env():
    if not trae_exe().is_file():
        pytest.skip(f"no Trae at {trae_exe()}; set GUIBRIDGE_TRAE_EXE")
    if not project_dir().is_dir():
        pytest.skip(f"GUIBRIDGE_PROJECT={project_dir() or '(unset)'} is not an isolated workspace")
    if not cdp_channel_ready():
        pytest.skip("gate G1 not passed: packages/perception/cdp.py still raises NotImplementedError")
    return {"exe": str(trae_exe()), "project": str(project_dir())}


async def call(session, tool: str, **arguments) -> dict:
    result = await session.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


@pytest.fixture
def live(live_env, tmp_path):
    """One `desktop-agent --mode live --mcp` subprocess per test, used as an external MCP client."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    database = tmp_path / "live-events.sqlite3"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO / "apps" / "desktop-agent" / "main.py"), "--mode", "live", "--db", str(database),
              "--mcp"],
        env={**os.environ, "GUIBRIDGE_TRAE_EXE": live_env["exe"], "GUIBRIDGE_PROJECT": live_env["project"]},
    )

    async def with_session(body):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await body(session)

    return (lambda body: asyncio.run(with_session(body))), database


def git_state(project: str) -> str:
    return subprocess.run(["git", "-C", project, "status", "--porcelain"], capture_output=True,
                          text=True).stdout


def test_the_live_server_offers_the_frozen_surface(live):
    run, _ = live

    async def body(session):
        return [tool.name for tool in (await session.list_tools()).tools]
    assert run(body) == ["gui.list_windows", "gui.inspect_window", "gui.find_element", "gui.perform_action",
                         "gui.get_snapshot", "trae.send_task", "trae.get_status", "trae.read_result"]


def test_send_status_read_closes_the_loop_without_touching_files(live, live_env):
    from events.store import EventStore

    run, database = live
    before = git_state(live_env["project"])

    async def body(session):
        windows = await call(session, "gui.list_windows")
        record = await call(session, "trae.send_task", project_path=live_env["project"], task=TASK_TEXT,
                            mode="chat")
        states = []
        for _ in range(120):
            states.append((await call(session, "trae.get_status", task_id=record["task_id"]))["state"])
            if states[-1] in ("claimed_done", "failed", "unknown", "awaiting_approval"):
                break
            await asyncio.sleep(0.5)
        result = await call(session, "trae.read_result", task_id=record["task_id"])
        return windows, record, states, result

    windows, record, states, result = run(body)
    assert windows["windows"], "the Trae window is not whitelisted; whitelist it in the Dashboard first"
    assert record["state"] == "submitted", record
    assert "running" in states, states
    assert states[-1] == "claimed_done", states
    assert result["untrusted"] is True and result["claimed_done"] is True
    assert result["reply_text"].strip()

    with EventStore(str(database)) as store:
        executed = [event["payload"] for event in store.events(kind="action", limit=1000)
                    if event["payload"]["success"]]
        transitions = [step["state"] for step in store.list_tasks()[0]["transitions"]]
    assert executed, "the live session performed no actions at all"
    assert [payload["semantic_id"] for payload in executed if not payload["verified"]] == []
    assert transitions[0] == "submitted" and "verified" not in transitions

    assert git_state(live_env["project"]) == before == ""


def test_agent_mode_is_never_assumed_authorized(live, live_env):
    run, _ = live

    async def body(session):
        return await call(session, "trae.send_task", project_path=live_env["project"], task=TASK_TEXT,
                          mode="agent")
    assert run(body)["error_code"] == "approval_required"
    assert git_state(live_env["project"]) == ""

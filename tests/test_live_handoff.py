"""S3 出口条件的 live 部分：独立仓库里让 Trae 实现「密码框显示/隐藏切换」，由 verifier 判定 verified。

默认被 `-m "not live"` 排除（docs/framework.md 工程纪律）。运行前提：

    GUIBRIDGE_TRAE_EXE   Trae 可执行文件（默认 D:\\Program\\Trae\\Trae.exe）
    GUIBRIDGE_PROJECT    隔离的目标工作区（独立 git 仓库；禁止指向用户真实项目）
    GUIBRIDGE_NODE       node 可执行文件（在 PATH 上时可不设）
    Trae 的审批模式已手动：live 侧的 MCP 工具没有 approval_token，人不先关掉自动审批，
    这条测试只会停在 awaiting_approval——那是设计意图，不是可以绕过的步骤。

与 test_live_trae.py 同理：任一前提缺失就整模块跳过，绝不退回 fixture 数据并声称 live 已验证。
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live

import handoff_demo  # noqa: E402
from handoff_demo import HandoffError, TaskPackage, handoff  # noqa: E402

BUTTON = "data-testid=\"toggle-password\""
TARGET_TEST = "tests/password-toggle.test.mjs"


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
    node = Path(handoff_demo._resolve_node())
    if not node.is_file():
        pytest.skip(f"acceptance command needs node; resolved {node}, set GUIBRIDGE_NODE")
    return {"exe": str(trae_exe()), "project": str(project_dir()), "node": str(node)}


async def call(session, tool: str, **arguments) -> dict:
    result = await session.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


@pytest.fixture
def live(live_env, tmp_path):
    """One `desktop-agent --mode live --mcp` subprocess per test, driven as an external MCP client."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    database = tmp_path / "handoff-events.sqlite3"
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

    return lambda body: asyncio.run(with_session(body))


class MCPClient:
    """The three handoff verbs over the frozen tool surface."""

    def __init__(self, run):
        self.run = run
        self.window_id = None

    def send_task(self, project_path, task, mode="chat", allow_files=None, acceptance=None, **opts):
        assert "approval_token" not in opts, "the MCP surface has no approval_token to leak"
        out = self.run(lambda s: call(s, "trae.send_task", project_path=project_path, task=task,
                                     mode=mode, allow_files=allow_files, acceptance=acceptance))
        if out.get("error_code"):
            raise ToolError(out["error_code"], out)
        return out

    def get_status(self, task_id):
        return self.run(lambda s: call(s, "trae.get_status", task_id=task_id))

    def read_result(self, task_id):
        return self.run(lambda s: call(s, "trae.read_result", task_id=task_id))


class ToolError(Exception):
    def __init__(self, code, envelope):
        self.code, self.envelope = code, envelope
        super().__init__(json.dumps(envelope, ensure_ascii=False))


def strip_reference_implementation(workspace: Path) -> str:
    """Live 演示配方（examples/demo-app/README.md）：只删实现，保留验收用例。

    删掉用例会让 `node --test` 空转通过，验收锚点必须留在仓库里。
    """
    text = (workspace / "index.html").read_text(encoding="utf-8")
    start, end = text.index("<button"), text.index("</button>") + len("</button>")
    (workspace / "index.html").write_text(text[:start] + text[end:], encoding="utf-8")
    handoff_demo.git(workspace, "add", "-A")
    return handoff_demo.git(workspace, *handoff_demo._SEED_IDENTITY, "commit",
                            "-m", "demo: remove the toggle so Trae has something to build")


def transitions(store, task_id) -> list[str]:
    return [entry["state"] for entry in store.get_task(task_id)["transitions"]]


def acceptance(workspace: Path, node: str) -> dict:
    """Run the planned acceptance command for real, outside any verification."""
    from execution.verifier import Verifier
    return Verifier().run_tests(workspace, [[node, "--test", "tests/*.test.mjs"]])[0]


def test_the_password_toggle_closes_the_loop_with_an_independent_verify(live, live_env, tmp_path):
    from events.store import EventStore
    from execution.verifier import Verifier

    run = live
    whitelisted = run(lambda s: call(s, "gui.list_windows"))["windows"]
    assert whitelisted, "the Trae window is not whitelisted; whitelist it in the Dashboard first"

    workspace = handoff_demo.prepare_workspace(tmp_path / "toggle")
    strip_reference_implementation(workspace)
    stripped = acceptance(workspace, live_env["node"])
    assert stripped["returncode"] != 0, "the stripped baseline must fail, or the check proves nothing"
    client = MCPClient(run)
    package = TaskPackage(
        project_path=str(workspace),
        task="为 index.html 的密码输入框新增显示/隐藏切换按钮，按钮文本随状态在「显示」「隐藏」之间切换，"
             "并在 tests/ 里补一条覆盖该切换逻辑的测试。不要改动其他文件。",
        allow_files=["index.html", "tests/"],
        test_commands=[[live_env["node"], "--test", "tests/*.test.mjs"]])

    with EventStore(str(tmp_path / "handoff-events.sqlite3")) as store:
        report = handoff(client, package, store=store, window_id=whitelisted[0]["window_id"],
                         verifier=Verifier(), poll_timeout=600.0)
        chain = transitions(store, report["task_id"])

    assert report["reply"]["untrusted"] is True
    assert report["states"][-1] == "claimed_done", report["states"]
    assert report["verification"]["tests"][0]["returncode"] == 0, report["verification"]["tests"]
    assert report["verification"]["changed_files"], "Trae changed nothing it could be credited for"
    assert report["final_state"] == "verified", report["verification"]["reasons"]
    assert (workspace / TARGET_TEST).is_file(), "the acceptance spec is gone; deleting the test is not proof"
    assert chain == ["submitted", "running", "claimed_done", "verified"], chain
    assert BUTTON in (workspace / "index.html").read_text(encoding="utf-8")


def test_an_unapproved_high_impact_click_leaves_the_workspace_alone(live, live_env, tmp_path):
    """No token exists on the tool surface, so agent mode cannot be assumed authorized."""
    from events.store import EventStore

    workspace = handoff_demo.prepare_workspace(tmp_path / "agent")
    package = TaskPackage(project_path=str(workspace), mode="agent",
                          test_commands=[[live_env["node"], "--test", "tests/*.test.mjs"]])
    with EventStore(str(tmp_path / "agent-events.sqlite3")) as store:
        with pytest.raises(HandoffError, match="awaits a human approval") as refused:
            handoff(MCPClient(live), package, store=store)
    assert refused.value.__cause__.code == "approval_required"
    assert subprocess.run(["git", "-C", str(workspace), "status", "--porcelain"], capture_output=True,
                          text=True).stdout == ""

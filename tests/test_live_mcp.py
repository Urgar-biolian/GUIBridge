"""Live S2 closure: one harmless chat-mode message through the external MCP surface.

Requires GUIBRIDGE_LIVE=1 and a running Trae with --remote-debugging-port=9222,
open on GUIBRIDGE_LIVE_PROJECT (an isolated repo, never a real project) with the IDE chat
panel visible. The prompt is fixed and harmless; no agent mode, no file edits, no
approval-mode changes are requested.
"""

import asyncio
import json
import os
import subprocess
import time

import pytest

# mcp_gateway speaks the MCP 1.x SDK; on 2.x this entry point moved, so the live closure skips.
try:
    from mcp.shared.memory import create_connected_server_and_client_session  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pytest.skip("the MCP gateway needs the mcp 1.x SDK (pip install 'mcp<2')", allow_module_level=True)

from mcp_gateway.server import build_server

PROJECT = os.environ.get("GUIBRIDGE_LIVE_PROJECT", "")
PROMPT = "请只回复 OK 两个字母，不要执行任何其他操作。"
PORT = int(os.environ.get("GUIBRIDGE_CDP_PORT", "9222"))

pytestmark = pytest.mark.live


def _call(result):
    return json.loads(result.content[0].text)


def _git_state() -> str:
    try:
        return subprocess.run(["git", "-C", PROJECT, "status", "--porcelain"],
                              capture_output=True, text=True, timeout=10).stdout
    except Exception as e:
        return f"git-unavailable: {e}"


def test_live_mcp_chat_round_trip(tmp_path):
    if os.environ.get("GUIBRIDGE_LIVE") != "1":
        pytest.skip("set GUIBRIDGE_LIVE=1 to run the live MCP round trip")
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=3):
            pass
    except Exception as e:
        pytest.skip(f"CDP unreachable on {PORT}: {e}")

    from router_engine import GUIBridgeEngine

    before = _git_state()
    engine = GUIBridgeEngine(port=PORT, db_path=str(tmp_path / "live.db"))
    engine.allow_window("trae")
    mcp = build_server(engine)

    async def scenario():
        async with create_connected_server_and_client_session(mcp) as session:
            windows = _call(await session.call_tool("gui.list_windows", {}))
            assert any(w.get("window_id") == "trae" and w.get("whitelisted") for w in windows["windows"])

            sent = _call(await session.call_tool("trae.send_task", {
                "project_path": PROJECT, "task": PROMPT, "mode": "chat"}))
            assert "error_code" not in sent, sent
            task_id = sent["task_id"]
            assert sent["state"] == "submitted"

            seen = []
            deadline = time.time() + 120
            status = sent
            while time.time() < deadline:
                status = _call(await session.call_tool("trae.get_status", {"task_id": task_id}))
                state = status.get("state")
                if not seen or seen[-1] != state:
                    seen.append(state)
                if state == "claimed_done":
                    break
                await asyncio.sleep(1.0)
            assert status.get("state") == "claimed_done", f"states={seen} last={status}"

            chain = [t["state"] for t in status.get("transitions") or []]
            assert chain[:3] == ["submitted", "running", "claimed_done"], chain

            result = _call(await session.call_tool("trae.read_result", {"task_id": task_id}))
            assert result["untrusted"] is True
            assert "OK" in (result.get("reply_text") or ""), result
            return task_id

    task_id = asyncio.run(scenario())
    after = _git_state()
    assert before == after, "workspace changed during the chat-only task"

    events = [e for e in engine.store.events_after(None, limit=500) if e["task_id"] == task_id]
    kinds = [e["kind"] for e in events]
    for k in ("task_submitted", "status_observed", "result_read"):
        assert k in kinds, kinds

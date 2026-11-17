import asyncio
import json

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_gateway.server import TOOL_SPECS, build_server


class FakeEngine:
    def __init__(self):
        self.calls = []

    def list_windows(self):
        return [{"window_id": "trae", "whitelisted": True}]

    def inspect_window(self, window_id, max_depth=18):
        return [{"id": "e1", "role": "button", "calibrated": False}]

    def find_element(self, window_id, **criteria):
        if criteria.get("semantic_id") == "boom":
            raise ToolBoom("boom requested")
        return []

    def perform_action(self, window_id, semantic_id, action, args=None, approval_token=None):
        return {"success": True, "verified": False, "error_code": None,
                "before_snapshot_id": "s1", "after_snapshot_id": "s2", "evidence": []}

    def get_snapshot(self, window_id):
        return {"snapshot_id": "s1", "elements_summary": [], "image_path": None}

    def send_task(self, project_path, task, **opts):
        self.calls.append((project_path, task, opts))
        return {"task_id": "t1", "state": "submitted", "app": "trae", "transitions": []}

    def get_status(self, task_id):
        return {"task_id": task_id, "state": "claimed_done", "signals": {}, "evidence": []}

    def read_result(self, task_id, max_chars=8000):
        return {"task_id": task_id, "reply_text": "OK", "untrusted": True,
                "claimed_done": True, "evidence": ["e"]}


class ToolBoom(RuntimeError):
    code = "conflict"


def _call(session_result):
    return json.loads(session_result.content[0].text)


def run(coro):
    return asyncio.run(coro)


def test_tool_surface_is_fixed_eight():
    assert len(TOOL_SPECS) == 8
    names = [spec[0] for spec in TOOL_SPECS]
    assert names[0] == "gui.list_windows" and names[-1] == "trae.read_result"


def test_server_exposes_eight_tools_and_calls_engine():
    engine = FakeEngine()
    mcp = build_server(engine)

    async def scenario():
        async with create_connected_server_and_client_session(mcp) as session:
            tools = await session.list_tools()
            assert [t.name for t in tools.tools] == [s[0] for s in TOOL_SPECS]
            windows = _call(await session.call_tool("gui.list_windows", {}))
            assert windows["windows"][0]["window_id"] == "trae"
            sent = _call(await session.call_tool("trae.send_task", {
                "project_path": r"D:\GitHub\Agui", "task": "hello"}))
            assert sent["task_id"] == "t1"
            result = _call(await session.call_tool("trae.read_result", {"task_id": "t1"}))
            assert result["untrusted"] is True
            error = _call(await session.call_tool("gui.find_element", {
                "window_id": "trae", "semantic_id": "boom"}))
            assert error["error_code"] == "conflict"

    run(scenario())
    assert engine.calls[0][0] == r"D:\GitHub\Agui"
    assert engine.calls[0][2]["mode"] == "chat"


def test_build_server_returns_fastmcp():
    assert isinstance(build_server(FakeEngine()), FastMCP)

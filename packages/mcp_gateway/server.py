"""MCP server: fixed 8-tool surface (PRD §6). Tools delegate to an Engine; no dynamic per-element tools.

Errors are returned as {error_code, message, evidence} envelopes using the frozen api.md codes.
"""

from __future__ import annotations

from typing import Protocol

import anyio

from mcp.server.fastmcp import FastMCP

TOOL_SPECS = [
    ("gui.list_windows", "List whitelisted windows", {}),
    ("gui.inspect_window", "Fused semantic elements of a window", {"window_id": "str", "max_depth": "int?"}),
    ("gui.find_element", "Find elements by semantic criteria", {"window_id": "str", "semantic_id": "str?", "role": "str?", "name": "str?"}),
    ("gui.perform_action", "Restricted action with verification", {"window_id": "str", "semantic_id": "str", "action": "str", "args": "dict?", "approval_token": "str?"}),
    ("gui.get_snapshot", "Window state snapshot", {"window_id": "str"}),
    ("trae.send_task", "Submit an IDE development task", {"project_path": "str", "task": "str", "mode": "str?", "allow_files": "list?", "acceptance": "dict?"}),
    ("trae.get_status", "Task state with evidence", {"task_id": "str"}),
    ("trae.read_result", "Assistant reply text (untrusted) + evidence", {"task_id": "str", "max_chars": "int?"}),
]


class Engine(Protocol):
    def list_windows(self) -> list[dict]: ...
    def inspect_window(self, window_id: str, max_depth: int = 18) -> list[dict]: ...
    def find_element(self, window_id: str, **criteria) -> list[dict]: ...
    def perform_action(self, window_id: str, semantic_id: str, action: str,
                       args: dict | None = None, approval_token: str | None = None) -> dict: ...
    def get_snapshot(self, window_id: str) -> dict: ...
    def send_task(self, project_path: str, task: str, **opts) -> dict: ...
    def get_status(self, task_id: str) -> dict: ...
    def read_result(self, task_id: str, max_chars: int = 8000) -> dict: ...


async def _guard(fn, *args, **kwargs) -> dict:
    # Sync engine methods may call asyncio.run internally; run them outside the MCP loop.
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except Exception as e:
        return {"error_code": getattr(e, "code", "unknown_state"),
                "message": str(e), "evidence": []}


def build_server(engine: Engine) -> FastMCP:
    mcp = FastMCP("guibridge")

    @mcp.tool(name="gui.list_windows", description="列出白名单内窗口")
    async def gui_list_windows() -> dict:
        return await _guard(lambda: {"windows": engine.list_windows()})

    @mcp.tool(name="gui.inspect_window", description="融合后的 GUIElement 列表（confidence 恒 calibrated=false）")
    async def gui_inspect_window(window_id: str, max_depth: int = 18) -> dict:
        return await _guard(lambda: {"elements": engine.inspect_window(window_id, max_depth)})

    @mcp.tool(name="gui.find_element", description="按 semantic_id / role / name 查找元素；无匹配返回空数组")
    async def gui_find_element(window_id: str, semantic_id: str | None = None,
                         role: str | None = None, name: str | None = None) -> dict:
        return await _guard(lambda: {"elements": engine.find_element(
            window_id, semantic_id=semantic_id, role=role, name=name)})

    @mcp.tool(name="gui.perform_action", description="受限动作；高影响控件需 approval_token")
    async def gui_perform_action(window_id: str, semantic_id: str, action: str,
                           args: dict | None = None, approval_token: str | None = None) -> dict:
        return await _guard(lambda: engine.perform_action(
            window_id, semantic_id, action, args, approval_token))

    @mcp.tool(name="gui.get_snapshot", description="窗口快照（元素摘要 + 截图路径）")
    async def gui_get_snapshot(window_id: str) -> dict:
        return await _guard(lambda: engine.get_snapshot(window_id))

    @mcp.tool(name="trae.send_task", description="向 Trae 提交任务；默认 chat 模式，agent 需审批")
    async def trae_send_task(project_path: str, task: str, mode: str = "chat",
                       allow_files: list[str] | None = None,
                       acceptance: dict | None = None) -> dict:
        return await _guard(lambda: engine.send_task(
            project_path, task, mode=mode, allow_files=allow_files, acceptance=acceptance))

    @mcp.tool(name="trae.get_status", description="任务状态 + 信号证据；冲突/超时为 unknown")
    async def trae_get_status(task_id: str) -> dict:
        return await _guard(lambda: engine.get_status(task_id))

    @mcp.tool(name="trae.read_result", description="末条助手回复（untrusted），仅 claimed_done")
    async def trae_read_result(task_id: str, max_chars: int = 8000) -> dict:
        return await _guard(lambda: engine.read_result(task_id, max_chars))

    return mcp


def main() -> None:
    from engine import GUIBridgeEngine

    build_server(GUIBridgeEngine()).run()


if __name__ == "__main__":
    main()

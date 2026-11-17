"""MCP server: fixed 8-tool surface (PRD §6). Tools delegate to an Engine; no dynamic per-element tools."""

from typing import Protocol

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


def build_server(engine: Engine):
    raise NotImplementedError("S2")
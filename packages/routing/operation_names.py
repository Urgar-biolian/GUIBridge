"""Draft operation-name crosswalk (R4 option b, design 11.4 item 7).

Pending B-line approval (R4). The draft measured capability table uses semantic
operation names (get_task_status / read_task_result) while the frozen TOOL_SPECS
and Engine methods use get_status / read_result (mcp_gateway/server.py:20-22,
33-35). This explicit crosswalk lets Phase 2 align routing lookup with tool
dispatch WITHOUT renaming the frozen specs or the measured table. It wires into
nothing frozen and changes no frozen contract; R4 option (a) would instead rename
the table keys to the frozen names and retire this module.
"""

from __future__ import annotations

# Frozen MCP tool names, verbatim from mcp_gateway/server.py TOOL_SPECS.
_TRAE_TOOL_BY_OPERATION = {
    "send_task": "trae.send_task",
    "get_task_status": "trae.get_status",
    "read_task_result": "trae.read_result",
}
_OPERATION_BY_TRAE_TOOL = {tool: op for op, tool in _TRAE_TOOL_BY_OPERATION.items()}


def tool_name(app: str, operation: str) -> str | None:
    """Capability-table (app, operation) -> frozen MCP tool name, or None."""
    if app != "trae":
        return None
    return _TRAE_TOOL_BY_OPERATION.get(operation)


def engine_method(app: str, operation: str) -> str | None:
    """Capability-table (app, operation) -> frozen Engine method name, or None."""
    tool = tool_name(app, operation)
    return tool.split(".", 1)[1] if tool else None


def capability_key(tool: str) -> tuple[str, str] | None:
    """Frozen MCP tool name -> capability-table (app, operation), or None."""
    operation = _OPERATION_BY_TRAE_TOOL.get(tool)
    return ("trae", operation) if operation else None
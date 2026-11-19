"""Draft operation-name crosswalk tests (R4 option b, design 11.4 item 7).

Locks the explicit mapping between the measured capability-table semantic names
and the frozen TOOL_SPECS / Engine names, plus a drift guard: every Trae table
operation must map to a frozen tool and every frozen Trae tool must map back to a
table key. Draft pending B-line approval; no frozen contract changed."""

from packages.routing.capability_table import load_capability_table
from packages.routing.operation_names import capability_key, engine_method, tool_name

# Verbatim frozen MCP tool names (mcp_gateway/server.py TOOL_SPECS).
FROZEN_TRAE_TOOLS = {"trae.send_task", "trae.get_status", "trae.read_result"}


def test_tool_name_maps_semantic_to_frozen():
    assert tool_name("trae", "send_task") == "trae.send_task"
    assert tool_name("trae", "get_task_status") == "trae.get_status"
    assert tool_name("trae", "read_task_result") == "trae.read_result"


def test_engine_method_names():
    assert engine_method("trae", "send_task") == "send_task"
    assert engine_method("trae", "get_task_status") == "get_status"
    assert engine_method("trae", "read_task_result") == "read_result"


def test_capability_key_reverse_maps():
    assert capability_key("trae.get_status") == ("trae", "get_task_status")
    assert capability_key("trae.read_result") == ("trae", "read_task_result")
    assert capability_key("trae.send_task") == ("trae", "send_task")


def test_round_trip():
    for operation in ("send_task", "get_task_status", "read_task_result"):
        assert capability_key(tool_name("trae", operation)) == ("trae", operation)


def test_non_trae_app_has_no_mcp_tool():
    assert tool_name("native-test", "invoke") is None
    assert engine_method("wechat", "send_message") is None
    assert capability_key("native-test.invoke") is None


def test_unknown_operation_returns_none():
    assert tool_name("trae", "bogus") is None
    assert capability_key("trae.bogus") is None


def test_crosswalk_covers_exactly_the_frozen_trae_tools():
    mapped = {tool_name("trae", op) for op in ("send_task", "get_task_status", "read_task_result")}
    assert mapped == FROZEN_TRAE_TOOLS


def test_no_drift_between_table_and_frozen_specs():
    table = load_capability_table()
    trae_ops = {op for (app, op) in table if app == "trae"}
    # every Trae table operation maps to a frozen tool ...
    for op in trae_ops:
        assert tool_name("trae", op) in FROZEN_TRAE_TOOLS
    # ... and every frozen Trae tool maps back to a key present in the table.
    for tool in FROZEN_TRAE_TOOLS:
        key = capability_key(tool)
        assert key is not None and key in table
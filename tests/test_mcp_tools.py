"""The frozen 8-tool MCP surface (PRD §6): every call is audited and errors travel as api.md envelopes.

The SDK executes synchronous tools in a worker thread, so these tests also pin the event store's
cross-thread use that a plain function call would never exercise.
"""

import asyncio
import json

import pytest
from adapters.trae import states
from mcp.server import TOOL_SPECS, build_server

DOC_NAMES = ["gui.list_windows", "gui.inspect_window", "gui.find_element", "gui.perform_action",
             "gui.get_snapshot", "trae.send_task", "trae.get_status", "trae.read_result"]
TASK = "请只回复 OK 两个字母，不要执行任何其他操作。"


def payload(result) -> dict:
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


@pytest.fixture
def surface(plane):
    return build_server(plane, plane.store)


@pytest.fixture
def call(plane, surface):
    def _call(tool: str, **arguments):
        return payload(asyncio.run(surface.call_tool(tool, arguments)))
    return _call


def tools_of(surface) -> dict:
    return {tool.name: tool for tool in asyncio.run(surface.list_tools())}


def test_the_surface_is_exactly_the_eight_documented_tools(surface):
    assert [name for name, _, _ in TOOL_SPECS] == DOC_NAMES
    assert list(tools_of(surface)) == DOC_NAMES


def test_instructions_warn_that_read_back_text_is_untrusted(surface):
    assert "untrusted" in surface.instructions.lower()


def test_schemas_expose_the_documented_arguments(surface):
    tools = tools_of(surface)
    assert set(tools["gui.perform_action"].input_schema["properties"]) == {
        "window_id", "semantic_id", "action", "args", "approval_token"}
    assert set(tools["trae.send_task"].input_schema["properties"]) == {
        "project_path", "task", "mode", "allow_files", "acceptance"}
    assert set(tools["trae.read_result"].input_schema["properties"]) == {"task_id", "max_chars"}


def test_list_windows_reports_only_whitelisted_windows(call, plane):
    windows = call("gui.list_windows")["windows"]
    assert [w["window_id"] for w in windows] == [plane.window_id]
    assert windows[0]["whitelisted"] is True


def test_inspect_returns_live_elements_and_find_relocates_by_semantic_id(call, plane):
    # `gui.inspect_window` is documented to return fused GUIElements; fusion is an S1 product
    # (packages/perception/fusion.py) and stays unimplemented, so before G1 the tool reports the raw
    # single-channel elements rather than pretending they were fused.
    elements = call("gui.inspect_window", window_id=plane.window_id)["elements"]
    assert {"selector", "role", "name"} <= set(elements[0])
    assert not any("confidence" in element or "bounds" in element for element in elements)

    found = call("gui.find_element", window_id=plane.window_id, semantic_id="trae.chat.composer")["elements"]
    assert [e["semantic_id"] for e in found] == ["trae.chat.composer"]
    assert found[0]["evidence"]["cdp_selector"] == ".chat-input-v2-input-box-editable"
    assert found[0]["calibrated"] is False


def test_a_missing_element_is_an_empty_result_not_an_error(call):
    assert call("gui.find_element", window_id="trae-main", semantic_id="trae.chat.nope")["elements"] == []


def test_a_window_outside_the_whitelist_is_refused(call):
    outcome = call("gui.inspect_window", window_id="other-editor")
    assert outcome["error_code"] == "window_not_allowed"


def test_conflicting_candidates_stop_execution_instead_of_guessing(call, plane, monkeypatch):
    def two_matches(window_id, selector):
        return [{"selector": selector, "role": "button", "name": "a"},
                {"selector": selector, "role": "button", "name": "b"}]
    monkeypatch.setattr(plane.channel, "query", two_matches)
    outcome = call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.new_session",
                   action="click")
    assert outcome["error_code"] == "conflict"
    assert plane.channel.actions == []


def test_a_high_impact_action_without_a_token_reaches_never_the_desktop(call, plane):
    outcome = call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.approval_mode",
                   action="click")
    assert outcome == {"success": False, "verified": False, "error_code": "approval_required",
                       "before_snapshot_id": "", "after_snapshot_id": "", "evidence": []}
    assert plane.channel.actions == []
    assert plane.store.pending_approvals()


def test_the_granted_token_lets_the_same_action_through(call, plane):
    """The tool surface switches the mode the same way: one gated `select`, verified by its label."""
    token = plane.grant_approval({"window_id": plane.window_id, "semantic_ids": ["trae.chat.approval_mode"],
                                  "actions": ["select"]})
    outcome = call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.approval_mode",
                   action="select", args={"value": states.MANUAL_APPROVAL_LABEL}, approval_token=token)
    assert outcome["verified"] is True
    assert plane.channel.approval_mode == "manual"


def test_the_tool_surface_cannot_pick_full_access(call, plane):
    """A tool caller may not widen what an agent does unattended, token or no token."""
    token = plane.grant_approval({"window_id": plane.window_id, "semantic_ids": ["trae.chat.approval_mode"],
                                  "actions": ["select"]})
    outcome = call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.approval_mode",
                   action="select", args={"value": "完全访问"}, approval_token=token)
    assert outcome["verified"] is False
    assert plane.channel.approval_mode == "auto"


def test_a_token_is_spent_the_first_time_it_is_used(call, plane):
    scope = {"window_id": plane.window_id, "semantic_ids": ["trae.chat.approval_mode"], "actions": ["click"]}
    token = plane.grant_approval(scope)
    call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.approval_mode",
         action="click", approval_token=token)
    plane.channel.approval_mode = "auto"
    reused = call("gui.perform_action", window_id="trae-main", semantic_id="trae.chat.approval_mode",
                  action="click", approval_token=token)
    assert reused["error_code"] == "approval_required"
    assert reused["verified"] is False


def test_snapshot_reports_element_summary_and_evidence_id(call, plane):
    snapshot = call("gui.get_snapshot", window_id="trae-main")
    assert snapshot["snapshot_id"]
    assert snapshot["ts"]
    assert snapshot["elements_summary"]["count"] == len(plane.channel.scan("trae-main"))
    assert "button" in snapshot["elements_summary"]["roles"]


def test_the_tool_surface_cannot_authorise_itself(call, plane):
    """docs/api.md gives `trae.send_task` no approval_token: a human clears auto-approval out of band."""
    blocked = call("trae.send_task", project_path="p", task=TASK, mode="chat")
    assert blocked["error_code"] == "approval_required"
    assert plane.store.pending_approvals()
    assert "submit" not in [entry["action"] for entry in plane.channel.actions]


def test_the_closed_loop_holds_through_the_tool_surface_alone(call, plane):
    call("trae.send_task", project_path="p", task=TASK, mode="chat")
    plane.channel.approval_mode = "manual"

    record = call("trae.send_task", project_path="p", task=TASK, mode="chat")
    assert record["state"] == "submitted"

    seen = []
    for _ in range(4):
        seen.append(call("trae.get_status", task_id=record["task_id"])["state"])
        if seen[-1] == "claimed_done":
            break
    assert seen[0] == "running" and seen[-1] == "claimed_done"

    result = call("trae.read_result", task_id=record["task_id"])
    assert result["untrusted"] is True and result["claimed_done"] is True
    assert "OK" in result["reply_text"]
    assert result["evidence"]
    states = [task["state"] for task in plane.store.list_tasks()]
    assert "verified" not in states


def test_status_of_a_task_this_session_does_not_know(call):
    assert call("trae.get_status", task_id="task_nope")["error_code"] == "unknown_state"


def test_every_call_is_written_to_the_event_store_including_failures(call, plane):
    call("gui.list_windows")
    call("gui.inspect_window", window_id="other-editor")
    call("trae.get_status", task_id="task_nope")
    calls = [event["payload"] for event in plane.store.events(kind="mcp_call")]
    assert [entry["tool"] for entry in calls] == ["gui.list_windows", "gui.inspect_window",
                                                   "trae.get_status"]
    assert [entry["ok"] for entry in calls] == [True, False, False]
    assert calls[1]["error_code"] == "window_not_allowed"


def test_task_payloads_are_previewed_not_dumped_whole(call, plane):
    long_task = "请只回复 OK。" + "补充说明。" * 60
    call("trae.send_task", project_path="p", task=long_task, mode="chat")
    recorded = [event["payload"]["params"]["task"] for event in plane.store.events(kind="mcp_call")
                if event["payload"]["tool"] == "trae.send_task"]
    assert all(len(text) <= 161 for text in recorded)
    assert any(text.endswith("…") for text in recorded)

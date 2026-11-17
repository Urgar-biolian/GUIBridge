"""PRD §7 state machine driven end-to-end against the pre-G1 simulation.

These cover the S2 exit conditions that do not need a desktop: every transition is backed by an
evidence id, `verified` is unreachable from the adapter, and nothing is submitted while the safety
gate is unsatisfied. Real-desktop behaviour is exercised by tests/test_live_trae.py.
"""

from pathlib import Path

import pytest
from adapters.trae.adapter import AdapterError

from main import build_plane

PROJECT = str(Path(__file__).resolve().parent)
TASK = "请只回复 OK 两个字母，不要执行任何其他操作。"


def approval(plane, semantic_id="trae.chat.approval_mode", action="click"):
    """The Dashboard half of the round-trip: a human grants a scoped, single-use token."""
    return plane.grant_approval({"window_id": plane.window_id, "semantic_ids": [semantic_id],
                                 "actions": [action]})


def actions_of(plane):
    return [entry["action"] for entry in plane.channel.actions]


def test_auto_approval_blocks_a_chat_task_until_a_human_acts(plane):
    with pytest.raises(AdapterError) as exc:
        plane.adapter.send_task(PROJECT, TASK)
    assert exc.value.code == "approval_required"
    assert "submit" not in actions_of(plane)
    assert plane.store.list_tasks()[0]["state"] == "failed"
    pending = plane.store.pending_approvals()
    assert pending and pending[0]["payload"]["scope"]["semantic_ids"] == ["trae.chat.approval_mode"]


def test_a_granted_token_is_what_lets_the_task_through(plane):
    record = plane.adapter.send_task(PROJECT, TASK, approval_token=approval(plane))
    assert record.state == "submitted"
    assert plane.channel.approval_mode == "manual"
    assert actions_of(plane) == ["click", "click", "select", "click", "click", "focus", "insert_text",
                                 "click", "submit"]
    assert [t["state"] for t in plane.store.task_transitions(record.task_id)] == ["submitted"]


def test_preconditions_are_proved_in_order_from_the_verified_locator_table(plane):
    plane.adapter.send_task(PROJECT, TASK, approval_token=approval(plane))
    sequence = plane.channel.actions
    assert sequence[0] == {"action": "click", "selector": ".icube-mode-tab-item-ide"}
    assert sequence[1]["selector"] == ".v2-agent-entry-btn"
    assert sequence[2] == {"action": "select", "selector": ".v2-agent-entry-btn", "value": "Chat"}
    assert sequence[3]["selector"] == "button[aria-label='自动审批']"
    assert sequence[4]["selector"] == "[data-testid=ai-chat-create-new-session]"
    assert sequence[5]["selector"] == ".chat-input-v2-input-box-editable"
    assert sequence[7]["selector"] == ".chat-input-v2-send-button"


def test_mode_is_selected_from_the_menu_leaf_never_the_wrapper(plane):
    plane.adapter.send_task(PROJECT, TASK, mode="agent", approval_token=approval(plane))
    assert plane.channel.session_mode == "Agent"
    assert plane.channel.menu_open is False
    selects = [entry for entry in plane.channel.actions if entry["action"] == "select"]
    assert selects == [{"action": "select", "selector": ".v2-agent-entry-btn", "value": "Agent"}]


def test_auto_approval_may_be_waived_only_by_an_explicit_opt_in(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    assert record.state == "submitted"
    assert plane.channel.approval_mode == "auto"
    assert plane.store.list_approvals() == []


def test_agent_mode_is_refused_before_the_desktop_is_touched_without_a_token(plane):
    with pytest.raises(AdapterError) as exc:
        plane.adapter.send_task(PROJECT, TASK, mode="agent")
    assert exc.value.code == "approval_required"
    assert plane.channel.actions == []
    assert plane.store.list_tasks() == []


def test_without_a_cdp_channel_the_adapter_refuses_a_coordinate_fallback(plane):
    plane.channel.available = lambda: False
    with pytest.raises(AdapterError) as exc:
        plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    assert exc.value.code == "unknown_state"
    assert plane.store.list_tasks() == []
    assert plane.channel.actions == []


def test_running_then_claimed_done_reads_back_the_reply(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    seen = []
    for _ in range(4):
        seen.append(plane.adapter.get_status(record.task_id).state)
        if seen[-1] == "claimed_done":
            break
    assert seen[0] == "running"
    assert seen[-1] == "claimed_done"
    assert "unknown" not in seen and "verified" not in seen

    result = plane.adapter.read_result(record.task_id)
    assert result["untrusted"] is True
    assert result["claimed_done"] is True
    assert "OK" in result["reply_text"]
    assert result["truncated"] is False


def test_status_tracks_transitions_with_an_evidence_id_each_step(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    for _ in range(4):
        if plane.adapter.get_status(record.task_id).state == "claimed_done":
            break
    chain = plane.store.task_transitions(record.task_id)
    assert [step["state"] for step in chain] == ["submitted", "running", "claimed_done"]
    assert all(step["evidence_id"] for step in chain)


def test_status_carries_the_signals_that_produced_the_state(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    assert plane.adapter.get_status(record.task_id).state == "running"
    assert plane.adapter.last_signals(record.task_id) == {"running_text": True, "stop_control": False,
                                                          "approval_prompt": False}


def test_reading_too_early_never_lifts_the_state(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    result = plane.adapter.read_result(record.task_id)
    assert result["claimed_done"] is False
    assert plane.store.get_task(record.task_id)["state"] == "submitted"
    assert plane.store.events(kind="read_result")


def test_read_result_declares_truncation(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    for _ in range(4):
        if plane.adapter.get_status(record.task_id).state == "claimed_done":
            break
    result = plane.adapter.read_result(record.task_id, max_chars=2)
    assert result["truncated"] is True
    assert result["full_length"] > 2
    assert result["reply_text"] == result["reply_text"][:2]


def test_an_unclassifiable_reply_times_out_as_unknown_rather_than_a_guess():
    plane = build_plane("simulated", status_timeout=-1.0)
    plane.channel.reply_plan = []
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    assert plane.adapter.get_status(record.task_id).state == "unknown"
    assert plane.store.events(kind="status_timeout")
    assert plane.store.get_task(record.task_id)["state"] == "unknown"


def test_verified_is_only_reachable_through_the_verifier(plane):
    record = plane.adapter.send_task(PROJECT, TASK, allow_auto_approval=True)
    with pytest.raises(PermissionError):
        plane.store.set_task_state(record.task_id, "verified", "snap_x")
    assert plane.adapter.verify(record.task_id, "snap_evidence").state == "verified"
    assert plane.store.get_task(record.task_id)["transitions"][-1]["evidence_id"] == "snap_evidence"


def test_an_unknown_task_id_is_reported_as_unknown_state(plane):
    with pytest.raises(AdapterError) as exc:
        plane.adapter.get_status("task_missing")
    assert exc.value.code == "unknown_state"


def test_probe_channels_keep_the_silently_broken_cli_as_a_candidate_only(plane):
    assert plane.adapter.probe_channels() == {"cdp": True, "cli_chat": False, "reply_archive": False}
    assert set(plane.adapter.capabilities()) == {"send_task", "get_status", "read_result"}

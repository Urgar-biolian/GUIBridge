"""Capability C pure-logic guards: reply extraction, approval-prompt text hints,
and the send_task safety preconditions. The mode/approval guards raise before any
CDP or store work, so they are verifiable with no live writes and no changes to
frozen contracts or the adapter itself."""

import pytest

from adapters.trae.adapter import AdapterError, TraeAdapter, extract_last_reply
from adapters.trae.states import has_approval_prompt


def test_extract_reply_after_marker():
    assert extract_last_reply("task text OK", "task text") == "OK"


def test_extract_uses_last_marker_occurrence():
    assert extract_last_reply("dup mid dup final", "dup") == "final"


def test_extract_no_marker_returns_whole_text():
    assert extract_last_reply("assistant reply", "absent marker") == "assistant reply"


def test_extract_empty_marker_returns_whole_text():
    assert extract_last_reply("  reply  ", "") == "reply"


def test_extract_empty_chat_returns_empty():
    assert extract_last_reply("", "marker") == ""
    assert extract_last_reply(None, None) == ""


def test_extract_marker_at_end_returns_empty():
    assert extract_last_reply("only marker", "only marker") == ""


def test_extract_strips_surrounding_whitespace():
    assert extract_last_reply("marker\n  reply \n", "marker") == "reply"


@pytest.mark.parametrize("text", ["等待审批", "需要审批", "需审批", "approval required"])
def test_approval_text_hints(text):
    assert has_approval_prompt(text) is True


def test_approval_visible_flag():
    assert has_approval_prompt("", visible=True) is True


def test_clean_text_no_approval():
    assert has_approval_prompt("已为你完成修改") is False
    assert has_approval_prompt(None) is False


def test_agent_mode_without_approval_rejected():
    adapter = TraeAdapter(port=0, store=None)
    with pytest.raises(AdapterError) as exc:
        adapter.send_task("proj", "task", mode="agent", approve_agent=False)
    assert exc.value.code == "approval_required"


def test_agent_mode_default_approve_false_rejected():
    adapter = TraeAdapter(port=0, store=None)
    with pytest.raises(AdapterError) as exc:
        adapter.send_task("proj", "task", mode="agent")
    assert exc.value.code == "approval_required"


def test_unsupported_mode_rejected():
    adapter = TraeAdapter(port=0, store=None)
    with pytest.raises(AdapterError) as exc:
        adapter.send_task("proj", "task", mode="edit")
    assert exc.value.code == "not_submitted"
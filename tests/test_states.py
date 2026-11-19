import pytest

from adapters.trae import states


def test_running_text_marks_running():
    assert states.detect_state("思考中", False, False, False) == "running"


@pytest.mark.parametrize("marker", states.RUNNING_TEXT)
def test_every_verified_runtime_marker_counts(marker):
    assert states.has_running_signal(f"前文 {marker} 后文")


def test_stop_control_alone_is_running():
    assert states.detect_state("", True, False, False) == "running"


def test_no_running_signal_plus_new_reply_is_claimed_done():
    assert states.detect_state("OK", False, True, False) == "claimed_done"


def test_idle_without_reply_is_unknown_not_claimed_done():
    assert states.detect_state("", False, False, False) == "unknown"


def test_conflicting_signals_report_unknown():
    assert states.detect_state("生成中", False, True, True) == "unknown"


def test_approval_prompt_wins_over_reply_claim():
    assert states.detect_state("", False, True, True) == "awaiting_approval"


def test_awaiting_approval_has_no_verified_marker_yet():
    """PROBE_REPORT 未验证项 3: the DOM signature is not measured, so nothing may claim it."""
    assert states.AWAITING_APPROVAL_MARKERS == ()
    assert states.has_approval_prompt("请批准执行 npm install") is False


def test_collect_signals_reports_all_three_surfaces():
    assert states.collect_signals("运行中", False) == {"running_text": True, "stop_control": False,
                                                       "approval_prompt": False}


def test_cdp_selector_follows_chain_order():
    from registry import load_registry
    registry, _ = load_registry()
    assert states.cdp_selector(registry, "trae.chat.composer") == ".chat-input-v2-input-box-editable"
    with pytest.raises(LookupError):
        states.cdp_selector(registry, "trae.chat.nope")


def _verifiers(fixture_dom):
    from registry import load_registry
    from simulated import SimulatedTrae
    registry, _ = load_registry()
    channel = SimulatedTrae(fixture_dom)
    window_id = channel.window["window_id"]
    return channel, states.build_verifiers(channel, window_id, registry)


def test_focusable_requires_send_button_to_leave_disabled(fixture_dom):
    channel, checks = _verifiers(fixture_dom)
    window = channel.window["window_id"]
    selector = ".chat-input-v2-input-box-editable"
    assert checks["focusable"](window, selector, {}) is False
    channel.insert_text(window, "hello")
    assert checks["focusable"](window, selector, {}) is True


def test_message_submitted_is_the_prd_postcondition(fixture_dom):
    channel, checks = _verifiers(fixture_dom)
    window = channel.window["window_id"]
    assert checks["message_submitted"](window, ".chat-input-v2-send-button", {"text": "hello"}) is False
    channel.insert_text(window, "hello")
    channel.click(window, ".chat-input-v2-send-button")
    assert checks["message_submitted"](window, ".chat-input-v2-send-button", {"text": "hello"}) is True


def test_mode_menu_open_and_selected_are_opposite_states(fixture_dom):
    channel, checks = _verifiers(fixture_dom)
    window = channel.window["window_id"]
    entry = ".v2-agent-entry-btn"
    assert checks["mode_menu_open"](window, entry, {}) is False
    channel.click(window, entry)
    assert checks["mode_menu_open"](window, entry, {}) is True
    channel.select(window, entry, "Chat")
    assert checks["session_mode_selected"](window, entry, {"value": "Chat"}) is True
    assert channel.session_mode == "Chat"


def test_approval_mode_manual_predicate(fixture_dom):
    channel, checks = _verifiers(fixture_dom)
    window = channel.window["window_id"]
    trigger = states.AUTO_APPROVAL_TRIGGER
    assert checks["approval_mode_manual"](window, trigger, {}) is False
    channel.click(window, trigger)
    # F10: the click only opens the popover, so the manual label may not be reported as switched on.
    assert checks["approval_mode_manual"](window, trigger, {}) is False
    assert checks["approval_menu_open"](window, trigger, {}) is True
    assert checks["approval_option_offered"](window, trigger, {}) is True
    channel.select(window, trigger, states.MANUAL_APPROVAL_LABEL)
    assert checks["approval_mode_manual"](window, trigger, {}) is True
    assert checks["approval_menu_open"](window, trigger, {}) is False


def test_a_popover_without_the_manual_row_is_evidence_of_its_own(fixture_dom):
    """`option_offered` is what tells a missing row apart from a menu that never opened."""
    channel, checks = _verifiers(fixture_dom)
    window = channel.window["window_id"]
    trigger = states.AUTO_APPROVAL_TRIGGER
    channel.approval_options = ["自动审批", "完全访问"]
    assert checks["approval_menu_open"](window, trigger, {}) is False
    assert checks["approval_option_offered"](window, trigger, {}) is False
    channel.approval_menu_open = True
    assert checks["approval_menu_open"](window, trigger, {}) is True
    assert checks["approval_option_offered"](window, trigger, {}) is False


# A lane pinned the same detectors from the other direction: an observed gate must outrank a reply
# node, and a transcript that mentions a gate must never be read as a completion. Both hold here;
# the word a hint produces is `unknown` rather than `awaiting_approval`, because PROBE_REPORT
# 未验证项 3 leaves the gate's DOM signature unmeasured and an unverified marker may not name a state.

@pytest.mark.parametrize("text", ["思考中", "正在生成中…", "运行中"])
def test_running_text_alone_is_running(text):
    assert states.detect_state(text, False, False, False) == "running"


def test_stop_control_counts_without_any_text():
    assert states.has_running_signal("", True)
    assert states.detect_state("", True, False, False) == "running"


def test_a_reply_is_only_a_claim_when_the_ui_has_stopped():
    assert states.detect_state("已为你完成修改", False, True, False) == "claimed_done"
    assert states.detect_state("已为你完成修改", False, False, False) == "unknown"


def test_an_observed_gate_while_idle_is_awaiting_approval():
    assert states.detect_state("需要审批", False, False, True) == "awaiting_approval"
    assert states.detect_state("思考中", False, False, True) == "awaiting_approval"
    assert states.detect_state("已为你完成修改", False, True, True) == "awaiting_approval"


@pytest.mark.parametrize("hint", states.APPROVAL_HINTS)
def test_an_approval_mention_never_becomes_a_completion_claim(hint):
    """Hard three-state requirement: the worst reading of a gate is a fake `claimed_done`."""
    assert states.detect_state(hint, False, True, False) != "claimed_done"
    assert states.detect_state(hint, False, True, False) == "unknown"

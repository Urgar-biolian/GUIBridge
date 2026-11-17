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
    trigger = "button[aria-label='自动审批']"
    assert checks["approval_mode_manual"](window, trigger, {}) is False
    channel.click(window, trigger)
    assert checks["approval_mode_manual"](window, trigger, {}) is True

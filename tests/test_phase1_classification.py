"""Phase 1 four-state classification checks (draft semantics, pending B approval)."""

from packages.focusguard.classify import classify
from packages.focusguard.monitor import (
    FocusRun,
    detect_unexpected_focus_switch,
    hook_dwell_ms,
)
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.routing.capability import Channel


def _run(*, focus_switch=False, cursor=0, external=False):
    snapshot = FocusSnapshot(
        foreground_hwnd=1, cursor_xy=(0, 0), target_active=True, ts=0.0
    )
    return FocusRun(
        result=None,
        before=snapshot,
        after=snapshot,
        unexpected_focus_switch=focus_switch,
        cursor_displacement=cursor,
        external_input_during_window=external,
    )


def test_unverified_or_error_is_failed():
    assert classify(_run(), False, None, Channel.UIA) is ResultState.FAILED
    assert classify(_run(), True, "boom", Channel.UIA) is ResultState.FAILED


def test_physical_input_always_counts_as_interference():
    assert (
        classify(_run(), True, None, Channel.FOREGROUND_INPUT)
        is ResultState.SUCCESS_WITH_INTERFERENCE
    )


def test_uia_clean_window_is_no_interference_observed():
    assert (
        classify(_run(), True, None, Channel.UIA)
        is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    )


def test_uia_focus_switch_counts_as_interference():
    assert (
        classify(_run(focus_switch=True), True, None, Channel.UIA)
        is ResultState.SUCCESS_WITH_INTERFERENCE
    )


def test_uia_cursor_displacement_counts_as_interference():
    assert (
        classify(_run(cursor=5), True, None, Channel.UIA)
        is ResultState.SUCCESS_WITH_INTERFERENCE
    )


def test_external_input_flag_alone_does_not_create_interference():
    assert (
        classify(_run(external=True), True, None, Channel.UIA)
        is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    )


def test_no_events_means_no_switch():
    assert detect_unexpected_focus_switch(100, [], []) is False


def test_events_equal_to_start_foreground_are_not_a_switch():
    assert detect_unexpected_focus_switch(100, [(0.0, 100)], [(0.0, 100)]) is False


def test_poll_only_switch_detected():
    assert detect_unexpected_focus_switch(100, [(0.0, 200)], []) is True


def test_hook_only_switch_detected_when_poll_misses():
    # Phase 1 E1c: 2 ms poll recorded nothing, event hook caught the transient switch.
    assert detect_unexpected_focus_switch(100, [], [(0.0, 200), (0.0, 100)]) is True


def test_hook_only_detection_flows_to_interference_state():
    run = _run()
    run.foreground_events = []
    run.hook_foreground_events = [(0.0, 200), (0.0, 100)]
    run.unexpected_focus_switch = detect_unexpected_focus_switch(
        run.before.foreground_hwnd, run.foreground_events, run.hook_foreground_events
    )
    assert classify(run, True, None, Channel.UIA) is ResultState.SUCCESS_WITH_INTERFERENCE


def test_hook_dwell_ms_precise_gap():
    assert hook_dwell_ms([(1000, 200), (1012, 100)], 200, 100) == 12.0


def test_hook_dwell_ms_missing_pair_returns_none():
    assert hook_dwell_ms([], 200, 100) is None
    assert hook_dwell_ms([(1000, 200)], 200, 100) is None
    assert hook_dwell_ms([(1000, 100)], 200, 100) is None


def test_hook_dwell_ms_handles_32bit_wrap():
    assert hook_dwell_ms([(0xFFFFFFF0, 200), (0x00000005, 100)], 200, 100) == 21.0
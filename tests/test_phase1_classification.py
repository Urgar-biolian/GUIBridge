"""Phase 1 four-state classification checks (draft semantics, pending B approval)."""

from packages.focusguard.classify import classify
from packages.focusguard.monitor import FocusRun
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
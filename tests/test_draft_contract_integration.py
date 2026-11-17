"""Composition tests: the draft contracts fit together end-to-end without the
frozen executor. Verifies operation metadata flows from the measured table into
the router impact gate and the retry policy, and that classification feeds retry.
Draft layer pending B-line approval; no engine/mcp_gateway wiring."""

from packages.focusguard.classify import classify
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.focusguard.retry_policy import decide_retry
from packages.routing.capability import Channel, OperationImpact
from packages.routing.capability_table import load_capability_table
from packages.routing.policy import InterferencePolicy
from packages.routing.router import StaticRouter


def _run(unexpected=False, displacement=0):
    snap = FocusSnapshot(foreground_hwnd=1, cursor_xy=(0, 0), target_active=True, ts=0.0)
    return FocusRun(
        result=None,
        before=snap,
        after=snap,
        unexpected_focus_switch=unexpected,
        cursor_displacement=displacement,
    )


def test_send_task_denied_by_router_and_retry():
    cap = load_capability_table()[("trae", "send_task")]
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is None  # unknown risk never auto-allowed
    retry = decide_retry(ResultState.UNCONFIRMED, idempotent=cap.idempotent)
    assert cap.idempotent is False
    assert retry.allow_retry is False
    assert retry.requires_approval is True


def test_read_interface_idempotent_metadata_enables_retry():
    cap = load_capability_table()[("trae", "read_task_result")]
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.APP_PROTOCOL
    assert decision.requires_approval is False
    assert cap.impact is OperationImpact.LOW
    retry = decide_retry(ResultState.UNCONFIRMED, idempotent=cap.idempotent)
    assert cap.idempotent is True
    assert retry.allow_retry is True


def test_native_invoke_classification_feeds_retry():
    cap = load_capability_table()[("native-test", "invoke")]
    decision = StaticRouter().route(cap, InterferencePolicy.BALANCED)
    assert decision.channel is Channel.UIA  # measured focus_switch allowed under BALANCED
    state = classify(_run(unexpected=True), verified=True, error=None, channel=Channel.UIA)
    assert state is ResultState.SUCCESS_WITH_INTERFERENCE
    retry = decide_retry(state, idempotent=cap.idempotent)
    assert retry.allow_retry is False  # succeeded, no retry


def test_native_invoke_failed_non_idempotent_denies_retry():
    cap = load_capability_table()[("native-test", "invoke")]
    state = classify(_run(), verified=False, error="invoke failed", channel=Channel.UIA)
    assert state is ResultState.FAILED
    retry = decide_retry(state, idempotent=cap.idempotent)
    assert cap.idempotent is False
    assert retry.allow_retry is False
    assert retry.requires_approval is True
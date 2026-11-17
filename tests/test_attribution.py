"""Draft external-input attribution tests (R3 option a, design open question 5).

Locks the candidate: a verified effect on a non-input channel is downgraded to
UNCONFIRMED when external input polluted the window; FOREGROUND_INPUT is exempt
(self-injection confound); a None measurement gap does not downgrade; errors and
unverified effects are unchanged. Draft pending B-line approval; classify() is
not replaced and nothing frozen is wired."""

from packages.focusguard.attribution import classify_with_attribution
from packages.focusguard.classify import classify
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.focusguard.retry_policy import decide_retry
from packages.routing.capability import Channel


def _run(external=None, focus_switch=False, displacement=0):
    snap = FocusSnapshot(foreground_hwnd=1, cursor_xy=(0, 0), target_active=True, ts=0.0)
    return FocusRun(
        result=None, before=snap, after=snap,
        unexpected_focus_switch=focus_switch,
        cursor_displacement=displacement,
        external_input_during_window=external,
    )


def test_non_input_channel_clean_window_stays_success():
    state = classify_with_attribution(_run(external=False), True, None, Channel.UIA)
    assert state is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED


def test_non_input_channel_external_input_downgrades_to_unconfirmed():
    state = classify_with_attribution(_run(external=True), True, None, Channel.UIA)
    assert state is ResultState.UNCONFIRMED


def test_external_input_downgrade_overrides_interference_success():
    state = classify_with_attribution(
        _run(external=True, focus_switch=True), True, None, Channel.UIA
    )
    assert state is ResultState.UNCONFIRMED


def test_none_measurement_gap_does_not_downgrade():
    state = classify_with_attribution(_run(external=None), True, None, Channel.UIA)
    assert state is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED


def test_app_protocol_non_input_channel_downgrades():
    state = classify_with_attribution(_run(external=True), True, None, Channel.APP_PROTOCOL)
    assert state is ResultState.UNCONFIRMED


def test_foreground_input_exempt_from_downgrade():
    # self-injection confound: flag is expected True, must not downgrade.
    state = classify_with_attribution(_run(external=True), True, None, Channel.FOREGROUND_INPUT)
    assert state is ResultState.SUCCESS_WITH_INTERFERENCE


def test_error_stays_failed_regardless_of_external_input():
    state = classify_with_attribution(_run(external=True), False, "boom", Channel.UIA)
    assert state is ResultState.FAILED


def test_unverified_effect_stays_unconfirmed():
    state = classify_with_attribution(_run(external=False), False, None, Channel.UIA)
    assert state is ResultState.UNCONFIRMED


# Composition with principle 6 (retry_policy): a pollution-downgraded effect must
# feed the retry decision, not be treated as a clean success.


def test_pollution_downgraded_non_idempotent_denies_auto_retry():
    run = _run(external=True, focus_switch=True)
    state = classify_with_attribution(run, True, None, Channel.UIA)
    assert state is ResultState.UNCONFIRMED
    decision = decide_retry(state, idempotent=False)
    assert decision.allow_retry is False
    assert decision.requires_approval is True


def test_pollution_downgraded_idempotent_may_retry_within_budget():
    run = _run(external=True, focus_switch=True)
    state = classify_with_attribution(run, True, None, Channel.UIA)
    decision = decide_retry(state, idempotent=True, attempts=0)
    assert decision.allow_retry is True


def test_clean_success_non_idempotent_needs_no_retry():
    run = _run(external=False, focus_switch=True)
    state = classify_with_attribution(run, True, None, Channel.UIA)
    assert state is ResultState.SUCCESS_WITH_INTERFERENCE
    decision = decide_retry(state, idempotent=False)
    assert decision.allow_retry is False
    assert decision.requires_approval is False


def test_attribution_adds_approval_guard_over_plain_classify():
    # Same polluted run: plain classify() calls it success (no approval flag),
    # attribution downgrades to UNCONFIRMED so a non-idempotent op needs approval.
    run = _run(external=True, focus_switch=True)
    plain = classify(run, True, None, Channel.UIA)
    assert plain is ResultState.SUCCESS_WITH_INTERFERENCE
    assert decide_retry(plain, idempotent=False).requires_approval is False
    guarded = classify_with_attribution(run, True, None, Channel.UIA)
    assert decide_retry(guarded, idempotent=False).requires_approval is True
"""Draft legacy-envelope bridge tests (design 11.4 item 1/2). Verifies the
four-state -> frozen success/verified/error_code mapping and explicitly locks
the information loss: legacy bools alone cannot distinguish UNCONFIRMED from
FAILED. Draft pending B-line approval; no frozen engine wiring."""

import pytest

from packages.focusguard.legacy_bridge import to_legacy_envelope
from packages.focusguard.outcome import ActionResult, ResultState
from packages.routing.capability import Channel, InterferenceRisk


def _result(state, risk=InterferenceRisk.FOCUS_SWITCH, evidence=None):
    return ActionResult(
        state=state,
        channel=Channel.UIA,
        risk=risk,
        effect_verified=state in (
            ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
            ResultState.SUCCESS_WITH_INTERFERENCE,
        ),
        evidence=evidence or {},
    )


@pytest.mark.parametrize(
    "state",
    [ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED, ResultState.SUCCESS_WITH_INTERFERENCE],
)
def test_success_maps_to_success_verified(state):
    env = to_legacy_envelope(_result(state))
    assert env.success is True
    assert env.verified is True
    assert env.error_code is None
    assert env.state is state


def test_interference_observed_flag():
    assert to_legacy_envelope(_result(ResultState.SUCCESS_WITH_INTERFERENCE)).interference_observed is True
    assert to_legacy_envelope(_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)).interference_observed is False


def test_failed_maps_to_failure_with_code():
    env = to_legacy_envelope(_result(ResultState.FAILED, evidence={"error_code": "conflict"}))
    assert env.success is False
    assert env.verified is False
    assert env.error_code == "conflict"


def test_failed_without_code_uses_default():
    env = to_legacy_envelope(_result(ResultState.FAILED))
    assert env.success is False
    assert env.error_code == "unknown_state"


def test_unconfirmed_maps_to_failure_without_code():
    env = to_legacy_envelope(_result(ResultState.UNCONFIRMED))
    assert env.success is False
    assert env.verified is False
    assert env.error_code is None
    assert env.state is ResultState.UNCONFIRMED


def test_legacy_bools_cannot_distinguish_unconfirmed_from_failed():
    # The frozen two-state envelope loses the principle-6 distinction; only the
    # preserved `state` field separates them. This collision is the documented
    # integration gap B-review must decide (extend api.md or accept degradation).
    unconfirmed = to_legacy_envelope(_result(ResultState.UNCONFIRMED))
    failed = to_legacy_envelope(_result(ResultState.FAILED))
    assert (unconfirmed.success, unconfirmed.verified) == (failed.success, failed.verified)
    assert unconfirmed.state is not failed.state


def test_risk_preserved_through_bridge():
    env = to_legacy_envelope(_result(ResultState.SUCCESS_WITH_INTERFERENCE, risk=InterferenceRisk.PHYSICAL_INPUT))
    assert env.risk is InterferenceRisk.PHYSICAL_INPUT
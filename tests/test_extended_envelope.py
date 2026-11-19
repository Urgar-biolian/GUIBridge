"""Draft extended-envelope candidate tests (R2 option a, design 11.4 item 1/2).

Locks the backward-compatible extension: legacy success/verified/error_code/
evidence fields are preserved AND state/risk/interference_observed are added so
UNCONFIRMED stays distinguishable from FAILED at the MCP boundary (principle 6).
Draft pending B-line approval; no frozen api.md change, no engine wiring."""

from packages.focusguard.extended_envelope import to_extended_envelope
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


def test_unconfirmed_and_failed_are_distinguishable():
    unconfirmed = to_extended_envelope(_result(ResultState.UNCONFIRMED))
    failed = to_extended_envelope(_result(ResultState.FAILED))
    # legacy bools alone still collapse both ...
    assert (unconfirmed.success, unconfirmed.verified) == (False, False)
    assert (failed.success, failed.verified) == (False, False)
    # ... but the added state field separates them (principle 6 preserved).
    assert unconfirmed.state is ResultState.UNCONFIRMED
    assert failed.state is ResultState.FAILED
    assert unconfirmed.to_dict()["state"] != failed.to_dict()["state"]


def test_success_with_interference_carries_risk_and_flag():
    env = to_extended_envelope(
        _result(ResultState.SUCCESS_WITH_INTERFERENCE, InterferenceRisk.FOCUS_SWITCH)
    )
    assert env.success is True and env.verified is True
    assert env.interference_observed is True
    assert env.risk is InterferenceRisk.FOCUS_SWITCH
    assert env.error_code is None


def test_success_no_interference_flag_false():
    env = to_extended_envelope(
        _result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED, InterferenceRisk.NONE)
    )
    assert env.success is True and env.verified is True
    assert env.interference_observed is False
    assert env.risk is InterferenceRisk.NONE


def test_to_dict_preserves_legacy_fields_and_adds_new():
    payload = to_extended_envelope(_result(ResultState.UNCONFIRMED)).to_dict()
    for legacy_key in ("success", "verified", "error_code", "evidence"):
        assert legacy_key in payload
    for new_key in ("state", "risk", "interference_observed"):
        assert new_key in payload
    assert payload["state"] == "unconfirmed"
    assert payload["risk"] == "focus_switch"


def test_failed_error_code_from_evidence():
    env = to_extended_envelope(
        _result(ResultState.FAILED, evidence={"error_code": "locator_missing"})
    )
    assert env.error_code == "locator_missing"
    assert env.success is False


def test_snapshot_ids_injected_and_default_none():
    default = to_extended_envelope(_result(ResultState.UNCONFIRMED))
    assert default.before_snapshot_id is None and default.after_snapshot_id is None
    wired = to_extended_envelope(
        _result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED),
        before_snapshot_id="snap_before",
        after_snapshot_id="snap_after",
    )
    assert wired.to_dict()["before_snapshot_id"] == "snap_before"
    assert wired.to_dict()["after_snapshot_id"] == "snap_after"


def test_evidence_ids_pass_through():
    env = to_extended_envelope(
        _result(ResultState.SUCCESS_WITH_INTERFERENCE),
        evidence_ids=["evt_1", "snap_2"],
    )
    assert env.evidence == ["evt_1", "snap_2"]
    assert to_extended_envelope(_result(ResultState.FAILED)).evidence == []
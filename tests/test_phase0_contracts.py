"""Phase 0 contract checks. Semantics stay provisional until B-line approval."""

from packages.focusguard.outcome import ActionResult, FocusSnapshot, ResultState
from packages.routing import (
    Capability,
    Channel,
    InterferencePolicy,
    InterferenceRisk,
    StaticRouter,
    is_allowed,
    requires_approval,
)


def _cap(channels, risk, unsupported_reason=None):
    return Capability(
        app="native-test",
        operation="click",
        channels=channels,
        risk=risk,
        unsupported_reason=unsupported_reason,
    )


def test_unknown_risk_is_never_allowed():
    for policy in InterferencePolicy:
        assert not is_allowed(policy, InterferenceRisk.UNKNOWN, approved=True)


def test_strict_denies_physical_input_without_approval():
    cap = _cap(
        {Channel.FOREGROUND_INPUT: True},
        {Channel.FOREGROUND_INPUT: InterferenceRisk.PHYSICAL_INPUT},
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is None
    assert decision.requires_approval is True


def test_strict_allows_physical_input_with_approval():
    cap = _cap(
        {Channel.FOREGROUND_INPUT: True},
        {Channel.FOREGROUND_INPUT: InterferenceRisk.PHYSICAL_INPUT},
    )
    decision = StaticRouter().route(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, approved=True
    )
    assert decision.channel is Channel.FOREGROUND_INPUT
    assert decision.requires_approval is True


def test_uia_preferred_over_denied_foreground():
    cap = _cap(
        {Channel.UIA: True, Channel.FOREGROUND_INPUT: True},
        {
            Channel.UIA: InterferenceRisk.LOGICAL_ONLY,
            Channel.FOREGROUND_INPUT: InterferenceRisk.PHYSICAL_INPUT,
        },
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.UIA
    assert decision.fallbacks == []


def test_app_protocol_preferred_over_uia():
    cap = _cap(
        {Channel.APP_PROTOCOL: True, Channel.UIA: True},
        {
            Channel.APP_PROTOCOL: InterferenceRisk.NONE,
            Channel.UIA: InterferenceRisk.LOGICAL_ONLY,
        },
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.APP_PROTOCOL
    assert decision.fallbacks == [Channel.UIA]


def test_balanced_allows_focus_switch_without_approval():
    assert is_allowed(InterferencePolicy.BALANCED, InterferenceRisk.FOCUS_SWITCH)
    assert not requires_approval(InterferencePolicy.BALANCED, InterferenceRisk.FOCUS_SWITCH)


def test_no_supported_channel_returns_reason():
    cap = _cap(
        {Channel.UIA: False},
        {Channel.UIA: InterferenceRisk.UNKNOWN},
        unsupported_reason="wechat 4.x: no UIA nodes",
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is None
    assert decision.reason == "wechat 4.x: no UIA nodes"


def test_action_result_has_four_states():
    assert {state.value for state in ResultState} == {
        "success_no_interference_observed",
        "success_with_interference",
        "failed",
        "unconfirmed",
    }
    snapshot = FocusSnapshot(foreground_hwnd=1, cursor_xy=(10, 20), target_active=True, ts=0.0)
    result = ActionResult(
        state=ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
        channel=Channel.UIA,
        risk=InterferenceRisk.LOGICAL_ONLY,
        effect_verified=True,
        focus_before=snapshot,
        focus_after=snapshot,
    )
    assert result.effect_verified
    assert result.unexpected_focus_switch is False

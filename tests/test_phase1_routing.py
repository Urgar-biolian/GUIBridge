"""Phase 1 routing corrections: measured UIA=FOCUS_SWITCH must drive policy decisions.

These lock the contract-review checklist (design doc 11.2) items 1 and 3 with
executable evidence. Draft semantics remain provisional until B-line approval.
"""

import pytest

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
        operation="invoke",
        channels=channels,
        risk=risk,
        unsupported_reason=unsupported_reason,
    )


def test_strict_denies_measured_uia_focus_switch_without_approval():
    cap = _cap(
        {Channel.UIA: True},
        {Channel.UIA: InterferenceRisk.FOCUS_SWITCH},
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is None
    assert decision.risk is InterferenceRisk.FOCUS_SWITCH
    assert decision.requires_approval is True


def test_strict_allows_measured_uia_focus_switch_with_approval():
    cap = _cap(
        {Channel.UIA: True},
        {Channel.UIA: InterferenceRisk.FOCUS_SWITCH},
    )
    decision = StaticRouter().route(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, approved=True
    )
    assert decision.channel is Channel.UIA
    assert decision.requires_approval is True


def test_balanced_prefers_uia_focus_switch_over_physical_input():
    cap = _cap(
        {Channel.UIA: True, Channel.FOREGROUND_INPUT: True},
        {
            Channel.UIA: InterferenceRisk.FOCUS_SWITCH,
            Channel.FOREGROUND_INPUT: InterferenceRisk.PHYSICAL_INPUT,
        },
    )
    decision = StaticRouter().route(cap, InterferencePolicy.BALANCED)
    assert decision.channel is Channel.UIA
    assert decision.requires_approval is False
    assert decision.fallbacks == []


def test_strict_falls_back_from_uia_focus_switch_to_logical_only():
    cap = _cap(
        {Channel.UIA: True, Channel.APP_PROTOCOL: True},
        {
            Channel.UIA: InterferenceRisk.FOCUS_SWITCH,
            Channel.APP_PROTOCOL: InterferenceRisk.LOGICAL_ONLY,
        },
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.APP_PROTOCOL
    assert decision.fallbacks == []


def test_same_risk_uses_channel_priority():
    cap = _cap(
        {Channel.APP_PROTOCOL: True, Channel.OFFICIAL_API: True},
        {
            Channel.APP_PROTOCOL: InterferenceRisk.NONE,
            Channel.OFFICIAL_API: InterferenceRisk.NONE,
        },
    )
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.OFFICIAL_API
    assert decision.fallbacks == [Channel.APP_PROTOCOL]


def test_supported_unknown_risk_channel_is_never_chosen():
    cap = _cap(
        {Channel.OCR_VISION: True},
        {Channel.OCR_VISION: InterferenceRisk.UNKNOWN},
    )
    decision = StaticRouter().route(
        cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True
    )
    assert decision.channel is None
    assert decision.requires_approval is False


@pytest.mark.parametrize(
    "policy,risk,approved,allowed",
    [
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.NONE, False, True),
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.LOGICAL_ONLY, False, True),
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.FOCUS_SWITCH, False, False),
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.FOCUS_SWITCH, True, True),
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.PHYSICAL_INPUT, False, False),
        (InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.PHYSICAL_INPUT, True, True),
        (InterferencePolicy.BALANCED, InterferenceRisk.FOCUS_SWITCH, False, True),
        (InterferencePolicy.BALANCED, InterferenceRisk.PHYSICAL_INPUT, False, False),
        (InterferencePolicy.BALANCED, InterferenceRisk.PHYSICAL_INPUT, True, True),
        (InterferencePolicy.FOREGROUND_ALLOWED, InterferenceRisk.PHYSICAL_INPUT, False, True),
        (InterferencePolicy.FOREGROUND_ALLOWED, InterferenceRisk.UNKNOWN, True, False),
    ],
)
def test_policy_approval_matrix(policy, risk, approved, allowed):
    assert is_allowed(policy, risk, approved) is allowed


def test_requires_approval_only_for_approvable_not_default_allowed():
    assert requires_approval(InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.FOCUS_SWITCH)
    assert requires_approval(InterferencePolicy.BALANCED, InterferenceRisk.PHYSICAL_INPUT)
    assert not requires_approval(InterferencePolicy.BALANCED, InterferenceRisk.FOCUS_SWITCH)
    assert not requires_approval(InterferencePolicy.FOREGROUND_ALLOWED, InterferenceRisk.PHYSICAL_INPUT)
    assert not requires_approval(InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.LOGICAL_ONLY)
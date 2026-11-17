"""Principle 7 contract tests: HIGH-impact operations require user approval
regardless of interference risk. Draft layer pending B-line approval."""

import pytest

from packages.routing.capability import Capability, Channel, InterferenceRisk, OperationImpact
from packages.routing.capability_table import load_capability_table
from packages.routing.policy import (
    InterferencePolicy,
    is_allowed,
    operation_requires_approval,
)
from packages.routing.router import StaticRouter

ALL_POLICIES = list(InterferencePolicy)


def _cap(impact, risk=InterferenceRisk.NONE, channel=Channel.OFFICIAL_API):
    return Capability(
        app="demo",
        operation="op",
        channels={channel: True},
        risk={channel: risk},
        impact=impact,
    )


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_high_impact_none_risk_denied_without_approval(policy):
    assert is_allowed(policy, InterferenceRisk.NONE, approved=False, impact=OperationImpact.HIGH) is False


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_high_impact_none_risk_allowed_with_approval(policy):
    assert is_allowed(policy, InterferenceRisk.NONE, approved=True, impact=OperationImpact.HIGH) is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_low_impact_none_risk_allowed_without_approval(policy):
    assert is_allowed(policy, InterferenceRisk.NONE, approved=False, impact=OperationImpact.LOW) is True


def test_high_impact_unknown_risk_denied_even_with_approval():
    assert is_allowed(
        InterferencePolicy.FOREGROUND_ALLOWED,
        InterferenceRisk.UNKNOWN,
        approved=True,
        impact=OperationImpact.HIGH,
    ) is False


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_high_impact_always_requires_approval(policy):
    assert operation_requires_approval(policy, InterferenceRisk.NONE, OperationImpact.HIGH) is True


def test_low_impact_none_risk_no_approval():
    assert operation_requires_approval(
        InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.NONE, OperationImpact.LOW
    ) is False


def test_low_impact_focus_switch_still_risk_approval():
    assert operation_requires_approval(
        InterferencePolicy.STRICT_NO_INTERFERENCE, InterferenceRisk.FOCUS_SWITCH, OperationImpact.LOW
    ) is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_router_denies_high_impact_without_approval(policy):
    decision = StaticRouter().route(_cap(OperationImpact.HIGH), policy, approved=False)
    assert decision.channel is None
    assert decision.requires_approval is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_router_allows_high_impact_with_approval_but_flags_it(policy):
    decision = StaticRouter().route(_cap(OperationImpact.HIGH), policy, approved=True)
    assert decision.channel is Channel.OFFICIAL_API
    assert decision.requires_approval is True


def test_router_low_impact_none_risk_clean():
    decision = StaticRouter().route(
        _cap(OperationImpact.LOW), InterferencePolicy.STRICT_NO_INTERFERENCE, approved=False
    )
    assert decision.channel is Channel.OFFICIAL_API
    assert decision.requires_approval is False


def test_table_send_task_high_impact_non_idempotent():
    cap = load_capability_table()[("trae", "send_task")]
    assert cap.impact is OperationImpact.HIGH
    assert cap.idempotent is False


def test_table_read_interfaces_low_impact_idempotent():
    table = load_capability_table()
    for op in ("get_task_status", "read_task_result"):
        cap = table[("trae", op)]
        assert cap.impact is OperationImpact.LOW
        assert cap.idempotent is True


def test_table_native_invoke_non_idempotent():
    cap = load_capability_table()[("native-test", "invoke")]
    assert cap.idempotent is False
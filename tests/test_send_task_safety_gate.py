"""Table-driven safety gate on the REAL Trae send_task deliverable entry.

Unlike test_phase1_routing.py (synthetic native-test/invoke fixtures), these
guards load the actual measured capability table and lock the routing/retry
consequences of send_task being HIGH impact + non-idempotent + unknown send-click
risk: it must never be auto-routable to an execution channel under ANY policy or
approval state until R5 measures the risk. Grounds principles 6/7 and the
"UNKNOWN never auto-allowed" discipline on the real artifact, not a proxy cap.
Draft layer pending B-line approval; nothing frozen wired, no live write."""

import pytest

from packages.focusguard.outcome import ResultState
from packages.focusguard.retry_policy import decide_retry
from packages.routing import (
    Channel,
    InterferencePolicy,
    InterferenceRisk,
    OperationImpact,
    StaticRouter,
    is_allowed,
    load_capability_table,
    operation_requires_approval,
)
from packages.routing.ocr_guard import route_ocr_aware

ALL_POLICIES = list(InterferencePolicy)
READ_OPERATIONS = ("get_task_status", "read_task_result")


@pytest.fixture(scope="module")
def table():
    return load_capability_table()


def test_send_task_real_entry_metadata(table):
    cap = table[("trae", "send_task")]
    assert cap.impact is OperationImpact.HIGH
    assert cap.idempotent is False
    assert cap.supported() == [Channel.APP_PROTOCOL]
    assert cap.risk_of(Channel.APP_PROTOCOL) is InterferenceRisk.UNKNOWN
    assert Channel.UIA not in cap.supported()


@pytest.mark.parametrize("policy", ALL_POLICIES)
@pytest.mark.parametrize("approved", [False, True])
def test_send_task_never_auto_routable_under_any_policy_or_approval(table, policy, approved):
    cap = table[("trae", "send_task")]
    decision = StaticRouter().route(cap, policy, approved=approved)
    assert decision.channel is None
    assert decision.risk is InterferenceRisk.UNKNOWN
    assert decision.requires_approval is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_send_task_ocr_aware_also_denied(table, policy):
    cap = table[("trae", "send_task")]
    decision = route_ocr_aware(cap, policy, approved=True)
    assert decision.channel is None


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_unknown_risk_dominates_approval_and_high_impact(policy):
    assert is_allowed(policy, InterferenceRisk.UNKNOWN, True, OperationImpact.HIGH) is False


@pytest.mark.parametrize("operation", READ_OPERATIONS)
def test_trae_read_entries_routable_under_strict_without_approval(table, operation):
    cap = table[("trae", operation)]
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.APP_PROTOCOL
    assert decision.risk is InterferenceRisk.NONE
    assert decision.requires_approval is False


def test_send_task_unconfirmed_non_idempotent_denies_auto_retry(table):
    cap = table[("trae", "send_task")]
    decision = decide_retry(ResultState.UNCONFIRMED, cap.idempotent)
    assert decision.allow_retry is False
    assert decision.requires_approval is True


def test_send_task_succeeded_needs_no_retry(table):
    cap = table[("trae", "send_task")]
    decision = decide_retry(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED, cap.idempotent)
    assert decision.allow_retry is False
    assert decision.requires_approval is False


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_send_task_high_impact_needs_approval_even_if_risk_measured_none(policy):
    """Principle 7 is orthogonal to risk: even after R5 measures send_task to NONE,
    HIGH impact still requires approval — measuring the risk must not auto-open it."""
    assert operation_requires_approval(policy, InterferenceRisk.NONE, OperationImpact.HIGH) is True
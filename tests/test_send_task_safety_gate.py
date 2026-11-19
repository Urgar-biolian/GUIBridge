"""Table-driven safety gate on the REAL Trae send_task deliverable entry.

Loads the actual measured capability table. send_task is HIGH impact +
non-idempotent; its send-click risk is now MEASURED none (clean FocusGuard trials
run 20261118T044436Z and 20261118T044518Z, the latter claimed_done + reply OK +
zero workspace change; a polluted first trial 20261118T044332Z was discarded).
These guards lock the consequences of that measurement: HIGH impact STILL requires
approval under every policy (principle 7, orthogonal to the now-none risk); without
an approval token it is never routable; with one it routes to APP_PROTOCOL and never
to OCR for a write (principle 3); non-idempotent UNCONFIRMED never auto-retries
(principle 6). Grounds principles 3/6/7 on the real artifact, not a proxy cap."""

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
    assert cap.risk_of(Channel.APP_PROTOCOL) is InterferenceRisk.NONE
    assert Channel.UIA not in cap.supported()


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_send_task_not_routable_without_approval(table, policy):
    cap = table[("trae", "send_task")]
    decision = StaticRouter().route(cap, policy, approved=False)
    assert decision.channel is None
    assert decision.requires_approval is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_send_task_routable_to_app_protocol_with_approval(table, policy):
    cap = table[("trae", "send_task")]
    decision = StaticRouter().route(cap, policy, approved=True)
    assert decision.channel is Channel.APP_PROTOCOL
    assert decision.risk is InterferenceRisk.NONE
    assert decision.requires_approval is True


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_send_task_ocr_aware_gates_approval_and_excludes_ocr(table, policy):
    cap = table[("trae", "send_task")]
    assert route_ocr_aware(cap, policy, approved=False).channel is None
    decision = route_ocr_aware(cap, policy, approved=True)
    assert decision.channel is Channel.APP_PROTOCOL
    assert Channel.OCR_VISION not in decision.fallbacks


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_unknown_risk_never_auto_allowed_even_with_approval(policy):
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
def test_send_task_high_impact_needs_approval_even_though_risk_measured_none(policy):
    """Principle 7 is orthogonal to risk: now that R5 measured send_task to NONE,
    HIGH impact still requires approval — measuring the risk must not auto-open it."""
    assert operation_requires_approval(policy, InterferenceRisk.NONE, OperationImpact.HIGH) is True
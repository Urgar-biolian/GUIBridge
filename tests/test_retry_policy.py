"""Retry-policy contract tests: task-book principle 6 (non-idempotent unconfirmed
operations must never auto-retry). Draft layer pending B-line approval."""

import pytest

from packages.focusguard.outcome import ResultState
from packages.focusguard.retry_policy import decide_retry


@pytest.mark.parametrize(
    "state",
    [ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED, ResultState.SUCCESS_WITH_INTERFERENCE],
)
@pytest.mark.parametrize("idempotent", [True, False])
def test_success_never_retries(state, idempotent):
    decision = decide_retry(state, idempotent)
    assert decision.allow_retry is False
    assert decision.requires_approval is False


@pytest.mark.parametrize("state", [ResultState.UNCONFIRMED, ResultState.FAILED])
def test_non_idempotent_never_auto_retries(state):
    decision = decide_retry(state, idempotent=False)
    assert decision.allow_retry is False
    assert decision.requires_approval is True


@pytest.mark.parametrize("state", [ResultState.UNCONFIRMED, ResultState.FAILED])
def test_idempotent_may_retry_within_budget(state):
    decision = decide_retry(state, idempotent=True, attempts=0, max_attempts=3)
    assert decision.allow_retry is True
    assert decision.requires_approval is False


@pytest.mark.parametrize("state", [ResultState.UNCONFIRMED, ResultState.FAILED])
def test_idempotent_budget_exhausted_denies(state):
    decision = decide_retry(state, idempotent=True, attempts=3, max_attempts=3)
    assert decision.allow_retry is False
    assert decision.requires_approval is True


def test_non_idempotent_denied_even_with_budget_remaining():
    decision = decide_retry(ResultState.UNCONFIRMED, idempotent=False, attempts=0, max_attempts=5)
    assert decision.allow_retry is False
    assert decision.requires_approval is True
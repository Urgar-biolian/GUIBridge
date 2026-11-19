"""Draft retry policy enforcing task-book principle 6 (pending B-line approval).

"无法确认是否成功的非幂等操作，禁止自动重复执行。" An UNCONFIRMED non-idempotent
operation must never auto-retry; it requires explicit human approval. Idempotent
operations may retry within a bounded budget. This module only decides; it does
not execute or wire into the frozen engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from .outcome import ResultState

_SUCCEEDED = (
    ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
    ResultState.SUCCESS_WITH_INTERFERENCE,
)


@dataclass(frozen=True)
class RetryDecision:
    allow_retry: bool
    reason: str
    requires_approval: bool = False


def decide_retry(
    state: ResultState,
    idempotent: bool,
    attempts: int = 0,
    max_attempts: int = 3,
) -> RetryDecision:
    if state in _SUCCEEDED:
        return RetryDecision(False, "already succeeded; no retry needed")

    if not idempotent:
        return RetryDecision(
            False,
            f"{state.value} non-idempotent operation must not auto-retry",
            requires_approval=True,
        )

    if attempts >= max_attempts:
        return RetryDecision(
            False,
            "retry budget exhausted",
            requires_approval=True,
        )

    return RetryDecision(True, f"{state.value} idempotent operation may retry")
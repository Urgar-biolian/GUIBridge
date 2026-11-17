"""Draft Phase 2 integration adapter (pending B-line approval; NOT wired into the
frozen engine/mcp_gateway/Dashboard, does not modify frozen actions.py/safety.py).

Composes the verified draft contracts into an executor-shaped surface aligned with
the frozen ActionExecutor/SafetyGate concerns, closing design 11.4 gaps:
  #4 approval double-gate — the frozen SafetyGate only gates by semantic_id keyword
     (HIGH_IMPACT set); it knows nothing of capability OperationImpact.HIGH or measured
     risk. This adapter layers the router's requires_approval on top: a HIGH-impact or
     approvable-risk operation must consume a valid approval token BEFORE execution,
     orthogonal to (not replacing) the frozen gate.
  #5 retry — any retry first calls decide_retry; non-idempotent UNCONFIRMED/FAILED never
     auto-retries (principle 6), idempotent retries only within budget.
  #6 four-state preservation — keeps the draft ActionResult (state/risk/focus evidence)
     and bridges to the frozen envelope via to_legacy_envelope without collapsing
     UNCONFIRMED into FAILED silently (the envelope still carries state/risk).

The execute/consume_approval callables are injected so this stays a testable draft and
wires into nothing frozen; at integration time execute is a FocusGuard-wrapped channel
call and consume_approval is SafetyGate.check_action / store.consume_approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from packages.focusguard.legacy_bridge import LegacyEnvelope, to_legacy_envelope
from packages.focusguard.outcome import ActionResult
from packages.focusguard.retry_policy import RetryDecision, decide_retry
from packages.routing.capability import Capability, Channel
from packages.routing.ocr_guard import route_ocr_aware
from packages.routing.policy import InterferencePolicy
from packages.routing.router import ChannelDecision


@dataclass(frozen=True)
class RoutedOutcome:
    decision: ChannelDecision
    executed: bool
    result: ActionResult | None
    retry: RetryDecision | None
    approval_id: str | None
    envelope: LegacyEnvelope | None
    denied_reason: str | None
    attempts: int


class RoutedExecutor:
    def __init__(
        self,
        execute: Callable[[Channel], ActionResult],
        consume_approval: Callable[[str, str, str], str] | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._execute = execute
        self._consume_approval = consume_approval
        self._max_attempts = max_attempts

    def run(
        self,
        capability: Capability,
        policy: InterferencePolicy,
        semantic_id: str,
        action: str,
        approval_token: str | None = None,
    ) -> RoutedOutcome:
        decision = route_ocr_aware(capability, policy, approved=bool(approval_token))
        if decision.channel is None:
            return RoutedOutcome(decision, False, None, None, None, None,
                                 "no_executable_channel", 0)

        approval_id = None
        if decision.requires_approval:
            if self._consume_approval is None:
                return RoutedOutcome(decision, False, None, None, None, None,
                                     "approval_required", 0)
            approval_id = self._consume_approval(semantic_id, action, approval_token)

        attempts = 0
        result = self._execute(decision.channel)
        retry = decide_retry(result.state, capability.idempotent, attempts, self._max_attempts)
        while retry.allow_retry:
            attempts += 1
            result = self._execute(decision.channel)
            retry = decide_retry(result.state, capability.idempotent, attempts, self._max_attempts)

        return RoutedOutcome(decision, True, result, retry, approval_id,
                             to_legacy_envelope(result), None, attempts)
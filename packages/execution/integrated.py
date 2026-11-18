"""G1 integration layer (approved R1 2026-11-17): composes the frozen-concern-aligned
drafts into one executable routed+guarded+four-state+audited execution surface.

Pipeline: route_ocr_aware (write excludes OCR, principle 3) -> approval double-gate
(injected consume_approval, principle 7) -> FocusGuard-wrapped channel operation ->
classify() four-state (principle 6) -> decide_retry budget (non-idempotent UNCONFIRMED
never auto-retries) -> evidence_bridge persists FocusSnapshots to store ids ->
R2a extended envelope. Does NOT modify frozen engine/ActionExecutor/SafetyGate; the
engine exposes this as an opt-in routed path at G1 merge (default path unchanged).

operation(channel) -> (verified: bool, error: str|None) is the channel-specific effect
check; the guard measures interference around it and classify() derives the state.
"""

from __future__ import annotations

from typing import Callable

from packages.focusguard.classify import classify
from packages.focusguard.evidence_bridge import to_api_envelope
from packages.focusguard.outcome import ActionResult, ResultState
from packages.routing.capability import Capability, Channel
from packages.routing.policy import InterferencePolicy

from .routed_executor import RoutedExecutor, RoutedOutcome


class IntegratedExecutor:
    def __init__(self, guard, store, window_id: str,
                 consume_approval: Callable[[str, str, str], str] | None = None,
                 max_attempts: int = 3) -> None:
        self._guard = guard
        self._store = store
        self._window_id = window_id
        self._consume_approval = consume_approval
        self._max_attempts = max_attempts

    def run(self, capability: Capability, policy: InterferencePolicy, semantic_id: str,
            action: str, operation: Callable[[Channel], tuple[bool, str | None]],
            approval_token: str | None = None) -> tuple[RoutedOutcome, object]:
        def execute(channel: Channel) -> ActionResult:
            risk = capability.risk_of(channel)
            try:
                run = self._guard.wrap_with_events(lambda: operation(channel))
                verified, error = run.result
            except Exception as e:  # channel backend failure is a confirmed error
                return ActionResult(
                    state=ResultState.FAILED, channel=channel, risk=risk,
                    effect_verified=False,
                    evidence={"error_code": "exec_error", "message": str(e)})
            state = classify(run, bool(verified), error, channel)
            return ActionResult(
                state=state, channel=channel, risk=risk, effect_verified=bool(verified),
                evidence={"error_code": error} if error else {},
                focus_before=run.before, focus_after=run.after,
                unexpected_focus_switch=run.unexpected_focus_switch)

        routed = RoutedExecutor(execute, self._consume_approval, self._max_attempts)
        outcome = routed.run(capability, policy, semantic_id, action, approval_token)
        envelope = (to_api_envelope(outcome.result, self._window_id, self._store)
                    if outcome.result is not None else None)
        return outcome, envelope
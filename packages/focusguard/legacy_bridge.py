"""Draft bridge from the four-state draft ActionResult to the frozen legacy
envelope semantics (``semantic.element.ActionResult``: success/verified/error_code).

Pending B-line approval. This module does NOT wire into the frozen
engine/mcp_gateway/Dashboard and does NOT change api.md. It makes design 11.4
item 1/2 executable: the legacy two-state bools cannot distinguish UNCONFIRMED
from FAILED (both fall to success=False/verified=False), so the original state
and risk are preserved alongside for a Phase 2 consumer to carry if B-review
chooses to extend the envelope. No new error code is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.routing.capability import InterferenceRisk

from .outcome import ActionResult, ResultState

_SUCCEEDED = (
    ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
    ResultState.SUCCESS_WITH_INTERFERENCE,
)


@dataclass(frozen=True)
class LegacyEnvelope:
    success: bool
    verified: bool
    error_code: str | None
    state: ResultState
    risk: InterferenceRisk
    interference_observed: bool


def to_legacy_envelope(result: ActionResult) -> LegacyEnvelope:
    if result.state in _SUCCEEDED:
        success, verified, error_code = True, True, None
    elif result.state is ResultState.FAILED:
        success, verified = False, False
        error_code = result.evidence.get("error_code") or "unknown_state"
    else:  # UNCONFIRMED: no confirmed error, success not positively confirmed
        success, verified, error_code = False, False, None
    return LegacyEnvelope(
        success=success,
        verified=verified,
        error_code=error_code,
        state=result.state,
        risk=result.risk,
        interference_observed=result.state is ResultState.SUCCESS_WITH_INTERFERENCE,
    )
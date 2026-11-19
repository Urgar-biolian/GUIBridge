"""Draft candidate for R2 option (a): backward-compatible MCP envelope extension.

Pending B-line approval (R2). Does NOT modify frozen api.md / semantic.element
and does NOT wire into the frozen engine/mcp_gateway. It preserves the frozen
legacy fields (success/verified/error_code/evidence) and ADDS state/risk/
interference_observed so UNCONFIRMED stays distinguishable from FAILED at the
MCP boundary (principle 6). Parallel to legacy_bridge.to_legacy_envelope, which
demonstrates option (b)'s degradation. Snapshot ids are injected by the Phase 2
store wiring (design 11.4 item 3); until then they default to None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.routing.capability import InterferenceRisk

from .legacy_bridge import to_legacy_envelope
from .outcome import ActionResult, ResultState


@dataclass(frozen=True)
class ExtendedEnvelope:
    success: bool
    verified: bool
    error_code: str | None
    state: ResultState
    risk: InterferenceRisk
    interference_observed: bool
    before_snapshot_id: str | None = None
    after_snapshot_id: str | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "verified": self.verified,
            "error_code": self.error_code,
            "state": self.state.value,
            "risk": self.risk.value,
            "interference_observed": self.interference_observed,
            "before_snapshot_id": self.before_snapshot_id,
            "after_snapshot_id": self.after_snapshot_id,
            "evidence": list(self.evidence),
        }


def to_extended_envelope(
    result: ActionResult,
    before_snapshot_id: str | None = None,
    after_snapshot_id: str | None = None,
    evidence_ids: list[str] | None = None,
) -> ExtendedEnvelope:
    legacy = to_legacy_envelope(result)
    return ExtendedEnvelope(
        success=legacy.success,
        verified=legacy.verified,
        error_code=legacy.error_code,
        state=legacy.state,
        risk=legacy.risk,
        interference_observed=legacy.interference_observed,
        before_snapshot_id=before_snapshot_id,
        after_snapshot_id=after_snapshot_id,
        evidence=list(evidence_ids or []),
    )
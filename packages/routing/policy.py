"""Interference policy (Phase 0 draft, pending B-line approval)."""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet

from .capability import InterferenceRisk, OperationImpact


class InterferencePolicy(str, Enum):
    STRICT_NO_INTERFERENCE = "strict_no_interference"
    BALANCED = "balanced"
    FOREGROUND_ALLOWED = "foreground_allowed"


_ALLOWED_WITHOUT_APPROVAL: dict[InterferencePolicy, FrozenSet[InterferenceRisk]] = {
    InterferencePolicy.STRICT_NO_INTERFERENCE: frozenset(
        {InterferenceRisk.NONE, InterferenceRisk.LOGICAL_ONLY}
    ),
    InterferencePolicy.BALANCED: frozenset(
        {InterferenceRisk.NONE, InterferenceRisk.LOGICAL_ONLY, InterferenceRisk.FOCUS_SWITCH}
    ),
    InterferencePolicy.FOREGROUND_ALLOWED: frozenset(
        {
            InterferenceRisk.NONE,
            InterferenceRisk.LOGICAL_ONLY,
            InterferenceRisk.FOCUS_SWITCH,
            InterferenceRisk.PHYSICAL_INPUT,
        }
    ),
}

_APPROVABLE: dict[InterferencePolicy, FrozenSet[InterferenceRisk]] = {
    InterferencePolicy.STRICT_NO_INTERFERENCE: frozenset(
        {InterferenceRisk.FOCUS_SWITCH, InterferenceRisk.PHYSICAL_INPUT}
    ),
    InterferencePolicy.BALANCED: frozenset({InterferenceRisk.PHYSICAL_INPUT}),
    InterferencePolicy.FOREGROUND_ALLOWED: frozenset(),
}


def is_allowed(
    policy: InterferencePolicy,
    risk: InterferenceRisk,
    approved: bool = False,
    impact: OperationImpact = OperationImpact.LOW,
) -> bool:
    if risk is InterferenceRisk.UNKNOWN:
        return False
    if impact is OperationImpact.HIGH and not approved:
        return False
    if risk in _ALLOWED_WITHOUT_APPROVAL[policy]:
        return True
    return approved and risk in _APPROVABLE[policy]


def requires_approval(policy: InterferencePolicy, risk: InterferenceRisk) -> bool:
    return risk in _APPROVABLE[policy] and risk not in _ALLOWED_WITHOUT_APPROVAL[policy]


def operation_requires_approval(
    policy: InterferencePolicy,
    risk: InterferenceRisk,
    impact: OperationImpact = OperationImpact.LOW,
) -> bool:
    """Principle 7: HIGH impact always needs approval, orthogonal to risk."""
    return impact is OperationImpact.HIGH or requires_approval(policy, risk)

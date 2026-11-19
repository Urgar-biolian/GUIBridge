"""Static capability router (Phase 0 draft, pending B-line approval)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .capability import Capability, Channel, InterferenceRisk
from .policy import InterferencePolicy, is_allowed, operation_requires_approval

_RISK_RANK: dict[InterferenceRisk, int] = {
    InterferenceRisk.NONE: 0,
    InterferenceRisk.LOGICAL_ONLY: 1,
    InterferenceRisk.FOCUS_SWITCH: 2,
    InterferenceRisk.PHYSICAL_INPUT: 3,
    InterferenceRisk.UNKNOWN: 4,
}

_CHANNEL_PRIORITY: tuple[Channel, ...] = (
    Channel.OFFICIAL_API,
    Channel.APP_PROTOCOL,
    Channel.CLI,
    Channel.UIA,
    Channel.VM_ISOLATED,
    Channel.OCR_VISION,
    Channel.FOREGROUND_INPUT,
)


@dataclass
class ChannelDecision:
    channel: Channel | None
    risk: InterferenceRisk
    requires_approval: bool
    fallbacks: list[Channel] = field(default_factory=list)
    reason: str = ""


class ExecutionRouter(Protocol):
    def route(
        self,
        capability: Capability,
        policy: InterferencePolicy,
        approved: bool = False,
    ) -> ChannelDecision: ...


class StaticRouter:
    """Deterministic router over a measured capability table; no online probing."""

    def route(
        self,
        capability: Capability,
        policy: InterferencePolicy,
        approved: bool = False,
    ) -> ChannelDecision:
        supported = capability.supported()
        if not supported:
            return ChannelDecision(
                None,
                InterferenceRisk.UNKNOWN,
                False,
                [],
                capability.unsupported_reason or "no supported channel",
            )

        ranked = sorted(
            supported,
            key=lambda channel: (
                _RISK_RANK[capability.risk_of(channel)],
                _CHANNEL_PRIORITY.index(channel),
            ),
        )
        allowed = [
            channel
            for channel in ranked
            if is_allowed(policy, capability.risk_of(channel), approved, capability.impact)
        ]
        if not allowed:
            best = ranked[0]
            return ChannelDecision(
                None,
                capability.risk_of(best),
                operation_requires_approval(policy, capability.risk_of(best), capability.impact),
                [],
                "policy denies all supported channels",
            )

        chosen = allowed[0]
        return ChannelDecision(
            chosen,
            capability.risk_of(chosen),
            operation_requires_approval(policy, capability.risk_of(chosen), capability.impact),
            allowed[1:],
            "selected by risk rank then channel priority",
        )

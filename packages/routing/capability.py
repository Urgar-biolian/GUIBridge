"""Execution channel capability model (Phase 0 draft, pending B-line approval)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class Channel(str, Enum):
    OFFICIAL_API = "official_api"
    CLI = "cli"
    UIA = "uia"
    APP_PROTOCOL = "app_protocol"
    OCR_VISION = "ocr_vision"
    FOREGROUND_INPUT = "foreground_input"
    VM_ISOLATED = "vm_isolated"


class InterferenceRisk(str, Enum):
    NONE = "none"
    LOGICAL_ONLY = "logical_only"
    FOCUS_SWITCH = "focus_switch"
    PHYSICAL_INPUT = "physical_input"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Capability:
    """Measured capability for one app x operation. Unknown channels stay absent."""

    app: str
    operation: str
    channels: Mapping[Channel, bool] = field(default_factory=dict)
    risk: Mapping[Channel, InterferenceRisk] = field(default_factory=dict)
    preconditions: Mapping[Channel, tuple[str, ...]] = field(default_factory=dict)
    unsupported_reason: str | None = None

    def supported(self) -> list[Channel]:
        return [channel for channel, ok in self.channels.items() if ok]

    def risk_of(self, channel: Channel) -> InterferenceRisk:
        return self.risk.get(channel, InterferenceRisk.UNKNOWN)

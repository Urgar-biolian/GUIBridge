"""Structured automation outcome (Phase 0 draft, pending B-line approval)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.routing.capability import Channel, InterferenceRisk


@dataclass(frozen=True)
class FocusSnapshot:
    foreground_hwnd: int
    cursor_xy: tuple[int, int]
    target_active: bool
    ts: float
    last_input_age_ms: float | None = None


class ResultState(str, Enum):
    SUCCESS_NO_INTERFERENCE_OBSERVED = "success_no_interference_observed"
    SUCCESS_WITH_INTERFERENCE = "success_with_interference"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"


@dataclass
class ActionResult:
    state: ResultState
    channel: Channel
    risk: InterferenceRisk
    effect_verified: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    focus_before: FocusSnapshot | None = None
    focus_after: FocusSnapshot | None = None
    unexpected_focus_switch: bool = False
    task_id: str | None = None

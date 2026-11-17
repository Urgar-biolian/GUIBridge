"""UIA pattern execution channel (Phase 0 draft, pending B-line approval).

Never falls back to SendInput; foreground input stays a separate channel.
"""

from __future__ import annotations

from typing import Protocol

from packages.focusguard.outcome import ActionResult
from packages.routing.capability import Channel


class UIAExecChannel(Protocol):
    def invoke(self, window_id: str, semantic_id: str) -> ActionResult: ...

    def set_value(self, window_id: str, semantic_id: str, value: str) -> ActionResult: ...

    def toggle(self, window_id: str, semantic_id: str) -> ActionResult: ...

    def read_state(self, window_id: str, semantic_id: str) -> dict: ...


class UiaPatternChannel:
    def __init__(self, guard=None, channel: Channel = Channel.UIA) -> None:
        self.guard = guard
        self.channel = channel

    def invoke(self, window_id: str, semantic_id: str) -> ActionResult:
        raise NotImplementedError("Phase 1: uiautomation InvokePattern + state readback")

    def set_value(self, window_id: str, semantic_id: str, value: str) -> ActionResult:
        raise NotImplementedError("Phase 1: uiautomation ValuePattern.SetValue + state readback")

    def toggle(self, window_id: str, semantic_id: str) -> ActionResult:
        raise NotImplementedError("Phase 1: uiautomation TogglePattern.Toggle + state readback")

    def read_state(self, window_id: str, semantic_id: str) -> dict:
        raise NotImplementedError("Phase 1: pattern state / control value readback")

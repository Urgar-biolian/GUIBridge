"""FocusGuard contract (Phase 0 draft, pending B-line approval).

Phase 1 implements monitoring; this module never injects input itself.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar

from .outcome import FocusSnapshot

T = TypeVar("T")


class FocusGuard(Protocol):
    def snapshot(self) -> FocusSnapshot: ...

    def wrap(self, action: Callable[[], T]) -> tuple[T, FocusSnapshot, FocusSnapshot]: ...


class Win32FocusGuard:
    def __init__(self, target_hwnd: int) -> None:
        self.target_hwnd = target_hwnd

    def snapshot(self) -> FocusSnapshot:
        raise NotImplementedError("Phase 1: GetForegroundWindow/GetCursorPos/IsWindowVisible")

    def wrap(self, action: Callable[[], T]) -> tuple[T, FocusSnapshot, FocusSnapshot]:
        raise NotImplementedError("Phase 1: before/after snapshot plus EVENT_SYSTEM_FOREGROUND log")

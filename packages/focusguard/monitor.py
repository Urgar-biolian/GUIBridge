"""Win32 FocusGuard implementation (Phase 1; contract still pending B approval)."""

from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass, field
from ctypes import wintypes
from typing import Callable, Protocol, TypeVar

from .outcome import FocusSnapshot

T = TypeVar("T")


class FocusGuard(Protocol):
    def snapshot(self) -> FocusSnapshot: ...

    def wrap(self, action: Callable[[], T]) -> tuple[T, FocusSnapshot, FocusSnapshot]: ...

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WM_QUIT = 0x0012
WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL


def _last_input_age_ms() -> float | None:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return float((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF)


def detect_unexpected_focus_switch(
    before_foreground: int,
    poll_events: list[tuple[float, int]],
    hook_events: list[tuple[float, int]],
) -> bool:
    """True if either sampler observed a foreground HWND other than the start.

    The event hook can catch transient switches the 2 ms poll misses (Phase 1
    E1c), so both sources are unioned rather than relying on the poll alone.
    """
    return any(
        fg != before_foreground for _, fg in (poll_events + hook_events)
    )


def hook_dwell_ms(
    hook_event_times: list[tuple[int, int]],
    occluder_hwnd: int,
    target_hwnd: int,
) -> float | None:
    """Precise foreground dwell from system event_time (ms), independent of
    Python dispatch latency. Returns the occluder->target gap, or None if the
    pair was not observed. event_time wraps at 32 bits; normalize the delta.
    """
    occ_ts = next((ts for ts, fg in hook_event_times if fg == occluder_hwnd), None)
    if occ_ts is None:
        return None
    tgt_ts = next(
        (ts for ts, fg in hook_event_times if fg == target_hwnd and ts != occ_ts),
        None,
    )
    if tgt_ts is None:
        return None
    return float((tgt_ts - occ_ts) & 0xFFFFFFFF)


def _foreground_hook_loop(events: list, event_times: list, ready: threading.Event, info: dict) -> None:
    def callback(hook, event, hwnd, id_object, id_child, event_thread, event_time):
        handle = int(hwnd or 0)
        events.append((time.time(), handle))
        event_times.append((int(event_time), handle))

    proc = WinEventProc(callback)
    handle = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,
        EVENT_SYSTEM_FOREGROUND,
        None,
        ctypes.cast(proc, ctypes.c_void_p),
        0,
        0,
        WINEVENT_OUTOFCONTEXT,
    )
    info["handle"] = handle
    info["tid"] = int(kernel32.GetCurrentThreadId())
    info["proc"] = proc
    ready.set()
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    if handle:
        user32.UnhookWinEvent(handle)


@dataclass
class FocusRun:
    result: object
    before: FocusSnapshot
    after: FocusSnapshot
    foreground_events: list[tuple[float, int]] = field(default_factory=list)
    cursor_trace: list[tuple[float, int, int]] = field(default_factory=list)
    unexpected_focus_switch: bool = False
    cursor_displacement: int = 0
    external_input_during_window: bool | None = None
    hook_foreground_events: list[tuple[float, int]] = field(default_factory=list)
    hook_event_times: list[tuple[int, int]] = field(default_factory=list)
    event_hook_active: bool = False


class Win32FocusGuard:
    def __init__(self, target_hwnd: int, interval: float = 0.002) -> None:
        self.target_hwnd = int(target_hwnd)
        self.interval = interval

    def snapshot(self) -> FocusSnapshot:
        foreground = int(user32.GetForegroundWindow() or 0)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        active = foreground == self.target_hwnd and bool(
            user32.IsWindowVisible(self.target_hwnd)
        )
        return FocusSnapshot(
            foreground_hwnd=foreground,
            cursor_xy=(point.x, point.y),
            target_active=active,
            ts=time.time(),
            last_input_age_ms=_last_input_age_ms(),
        )

    def wrap_with_events(self, action, settle: float = 0.05) -> FocusRun:
        before = self.snapshot()
        stop = threading.Event()
        events: list[tuple[float, int]] = []
        trace: list[tuple[float, int, int]] = []
        last_foreground = [before.foreground_hwnd]
        hook_events: list[tuple[float, int]] = []
        hook_event_times: list[tuple[int, int]] = []
        hook_info: dict = {}
        hook_ready = threading.Event()

        def sample() -> None:
            while not stop.is_set():
                foreground = int(user32.GetForegroundWindow() or 0)
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                now = time.time()
                trace.append((now, point.x, point.y))
                if foreground != last_foreground[0]:
                    events.append((now, foreground))
                    last_foreground[0] = foreground
                time.sleep(self.interval)

        sampler = threading.Thread(target=sample, daemon=True)
        hook_thread = threading.Thread(
            target=_foreground_hook_loop,
            args=(hook_events, hook_event_times, hook_ready, hook_info),
            daemon=True,
        )
        sampler.start()
        hook_thread.start()
        hook_ready.wait(timeout=1.0)
        try:
            result = action()
        finally:
            time.sleep(settle)
            stop.set()
            sampler.join(timeout=1.0)
            tid = hook_info.get("tid")
            if tid:
                user32.PostThreadMessageW(int(tid), WM_QUIT, 0, 0)
            hook_thread.join(timeout=1.0)

        after = self.snapshot()
        if after.foreground_hwnd != last_foreground[0]:
            events.append((after.ts, after.foreground_hwnd))

        unexpected = detect_unexpected_focus_switch(
            before.foreground_hwnd, events, hook_events
        )
        displacement = max(
            (
                max(abs(x - before.cursor_xy[0]), abs(y - before.cursor_xy[1]))
                for _, x, y in trace
            ),
            default=0,
        )
        external_input = None
        if before.last_input_age_ms is not None and after.last_input_age_ms is not None:
            window_ms = (after.ts - before.ts) * 1000
            external_input = after.last_input_age_ms < before.last_input_age_ms + window_ms - 20
        return FocusRun(
            result=result,
            before=before,
            after=after,
            foreground_events=events,
            cursor_trace=trace,
            unexpected_focus_switch=unexpected,
            cursor_displacement=displacement,
            external_input_during_window=external_input,
            hook_foreground_events=hook_events,
            hook_event_times=hook_event_times,
            event_hook_active=bool(hook_info.get("handle")),
        )

    def wrap(self, action):
        run = self.wrap_with_events(action)
        return run.result, run.before, run.after

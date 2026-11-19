"""E7 background window-message input: PostMessage/SendMessage measured by FocusGuard.

Question: can WM_*/BM_* messages delivered to a BACKGROUND window produce the effect
without moving the system cursor or switching the foreground window? Controlled local
targets only (native_test_app standard controls; selfdrawn_app painted UI). No real-app
writes, no Trae interaction.

Provisional channel label "background_message". The frozen Channel enum is NOT modified.
classify() is called on its measured (non-FOREGROUND_INPUT) branch, which is channel
agnostic: verified + no focus switch + cursor 0 => SUCCESS_NO_INTERFERENCE_OBSERVED.
Risk is reported as provisional LOGICAL_ONLY pending per-app measurement; a posted
message that the app ignores yields UNCONFIRMED, never a claimed success.
"""

from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes

from packages.focusguard.classify import classify
from packages.focusguard.monitor import FocusRun, Win32FocusGuard
from packages.routing.capability import Channel, InterferenceRisk

PROVISIONAL_CHANNEL = "background_message"

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetDlgItem.restype = wintypes.HWND

BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CHAR = 0x0102
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

BUTTON_ID = 1001
EDIT_ID = 1002
CHECKBOX_ID = 1003
STATUS_ID = 1004


def child_hwnd(parent: int, ctrl_id: int) -> int:
    return int(user32.GetDlgItem(wintypes.HWND(int(parent)), ctrl_id) or 0)


def get_text(hwnd: int) -> str:
    hwnd = int(hwnd)
    length = int(user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0))
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buf))
    return buf.value


def _makelparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def clicked_count(status: str) -> int | None:
    match = re.search(r"clicked=(\d+)", status)
    return int(match.group(1)) if match else None


def _measure(guard: Win32FocusGuard, action, verified_fn, evidence, op: str) -> dict:
    error = None
    try:
        run = guard.wrap_with_events(action)
    except Exception as exc:  # noqa: BLE001 - probe records, never crashes the matrix
        run = FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot())
        error = repr(exc)
    time.sleep(0.05)
    verified = bool(verified_fn()) if error is None else False
    # evidence may be a callable so "after" fields are read post-action, not at arg-build time.
    evidence = dict(evidence() if callable(evidence) else evidence)
    # UIA here only selects classify's measured (non-foreground) branch; the provisional
    # channel name is recorded separately so no frozen enum value is implied.
    state = classify(run, verified, error, Channel.UIA)
    evidence.update(
        {
            "op": op,
            "provisional_channel": PROVISIONAL_CHANNEL,
            "classify_branch": "measured(non-foreground)",
            "cursor_displacement": run.cursor_displacement,
            "unexpected_focus_switch": run.unexpected_focus_switch,
            "external_input_during_window": run.external_input_during_window,
            "foreground_events": [fg for _, fg in run.foreground_events],
            "hook_foreground_events": [fg for _, fg in run.hook_foreground_events],
            "event_hook_active": run.event_hook_active,
            "focus_before": run.before.foreground_hwnd,
            "focus_after": run.after.foreground_hwnd,
        }
    )
    if error:
        evidence["error"] = error
    return {
        "state": state.value,
        "provisional_channel": PROVISIONAL_CHANNEL,
        "risk": InterferenceRisk.LOGICAL_ONLY.value,
        "effect_verified": verified,
        "evidence": evidence,
    }


def bm_click_button(parent: int, guard: Win32FocusGuard) -> dict:
    status = child_hwnd(parent, STATUS_ID)
    button = child_hwnd(parent, BUTTON_ID)
    before = get_text(status)
    count_before = clicked_count(before)

    def action():
        user32.PostMessageW(button, BM_CLICK, 0, 0)

    def verified():
        after = clicked_count(get_text(status))
        return count_before is not None and after == count_before + 1

    return _measure(guard, action, verified,
                    lambda: {"status_before": before, "status_after": get_text(status)}, "bm_click_button")


def raw_click_button(parent: int, guard: Win32FocusGuard) -> dict:
    """Coordinate mouse messages to the button child, cursor parked elsewhere."""
    status = child_hwnd(parent, STATUS_ID)
    button = child_hwnd(parent, BUTTON_ID)
    before = get_text(status)
    count_before = clicked_count(before)
    cx, cy = 75, 16  # button child client centre (150x32)

    def action():
        lp = _makelparam(cx, cy)
        user32.PostMessageW(button, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        user32.PostMessageW(button, WM_LBUTTONUP, 0, lp)

    def verified():
        after = clicked_count(get_text(status))
        return count_before is not None and after == count_before + 1

    return _measure(guard, action, verified,
                    lambda: {"status_before": before, "status_after": get_text(status),
                             "client_xy": [cx, cy]}, "raw_click_button")


def settext_edit(parent: int, guard: Win32FocusGuard, value: str) -> dict:
    edit = child_hwnd(parent, EDIT_ID)
    before = get_text(edit)

    def action():
        buf = ctypes.create_unicode_buffer(value)
        user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.addressof(buf))

    return _measure(guard, action, lambda: get_text(edit) == value,
                    lambda: {"value_before": before, "value_after": get_text(edit), "expected": value},
                    "settext_edit")


def char_edit(parent: int, guard: Win32FocusGuard, value: str) -> dict:
    edit = child_hwnd(parent, EDIT_ID)
    empty = ctypes.create_unicode_buffer("")
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.addressof(empty))
    before = get_text(edit)

    def action():
        for ch in value:
            user32.PostMessageW(edit, WM_CHAR, ord(ch), 0)

    return _measure(guard, action, lambda: get_text(edit) == value,
                    lambda: {"value_before": before, "value_after": get_text(edit), "expected": value},
                    "char_edit")


def bm_click_checkbox(parent: int, guard: Win32FocusGuard) -> dict:
    checkbox = child_hwnd(parent, CHECKBOX_ID)
    before = int(user32.SendMessageW(checkbox, BM_GETCHECK, 0, 0))

    def action():
        user32.PostMessageW(checkbox, BM_CLICK, 0, 0)

    def verified():
        return int(user32.SendMessageW(checkbox, BM_GETCHECK, 0, 0)) != before

    return _measure(guard, action, verified,
                    lambda: {"check_before": before,
                             "check_after": int(user32.SendMessageW(checkbox, BM_GETCHECK, 0, 0))},
                    "bm_click_checkbox")


def selfdrawn_raw_click(hwnd: int, guard: Win32FocusGuard, title_reader) -> dict:
    """Coordinate mouse messages to a painted (no child controls) background window.

    title_reader returns the current window title; the target mirrors its click count
    into the title under --title-status so the effect is readable without OCR.
    """
    before = title_reader()
    count_before = clicked_count(before) or 0
    cx, cy = 95, 68  # painted button rect (20,50)-(170,86) centre

    def action():
        lp = _makelparam(cx, cy)
        user32.PostMessageW(int(hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lp)
        user32.PostMessageW(int(hwnd), WM_LBUTTONUP, 0, lp)

    def verified():
        after = clicked_count(title_reader()) or 0
        return after == count_before + 1

    return _measure(guard, action, verified,
                    lambda: {"title_before": before, "title_after": title_reader(),
                             "client_xy": [cx, cy]}, "selfdrawn_raw_click")
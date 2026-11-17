"""Controlled Win32 target for Phase 1 UIA experiments.

Runs a single window (title "GUIBridge UIA Test Target") with standard
BUTTON / EDIT / CHECKBOX / STATIC controls. Standard controls are exposed
through the MSAA-to-UIA bridge, which is what E1/E3 exercise.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import threading
from ctypes import wintypes

APP_TITLE = "GUIBridge UIA Test Target"
WINDOW_CLASS = "GUIBridgeTestWindow"
BUTTON_ID = 1001
EDIT_ID = 1002
CHECKBOX_ID = 1003
STATUS_ID = 1004

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_SETFONT = 0x0030
WM_LBUTTONDOWN = 0x0201
BN_CLICKED = 0
BM_GETCHECK = 0x00F0
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_BORDER = 0x00800000
WS_EX_TOPMOST = 0x00000008
BS_PUSHBUTTON = 0x00000000
BS_AUTOCHECKBOX = 0x00000003
ES_AUTOHSCROLL = 0x0080
SS_LEFT = 0x00000000
CW_USEDEFAULT = 0x80000000
DEFAULT_GUI_FONT = 17
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SW_SHOWNOACTIVATE = 4


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.RegisterClassW.restype = wintypes.ATOM
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
gdi32.GetStockObject.restype = wintypes.HANDLE

_state = {
    "hwnd": None,
    "button": None,
    "edit": None,
    "checkbox": None,
    "status": None,
    "clicks": 0,
    "checked": False,
}
_click_counts = {"target": 0, "occluder": 0}


def _set_status(text: str) -> None:
    if _state["status"]:
        user32.SetWindowTextW(_state["status"], text)


def _render_status() -> None:
    _set_status(
        f"status: clicked={_state['clicks']} checkbox={'on' if _state['checked'] else 'off'}"
    )


def _make_child(class_name, text, style, x, y, w, h, ctrl_id):
    return user32.CreateWindowExW(
        0,
        class_name,
        text,
        WS_CHILD | WS_VISIBLE | style,
        x,
        y,
        w,
        h,
        _state["hwnd"],
        wintypes.HMENU(ctrl_id),
        kernel32.GetModuleHandleW(None),
        None,
    )


def _window_proc(hwnd, msg, wparam, lparam):
    if msg == WM_CREATE:
        _state["hwnd"] = hwnd
        font = gdi32.GetStockObject(DEFAULT_GUI_FONT)
        _state["button"] = _make_child(
            "BUTTON", "Run action", BS_PUSHBUTTON, 20, 20, 150, 32, BUTTON_ID
        )
        _state["edit"] = _make_child(
            "EDIT", "initial", WS_BORDER | ES_AUTOHSCROLL, 20, 70, 340, 28, EDIT_ID
        )
        _state["checkbox"] = _make_child(
            "BUTTON", "Enable option", BS_AUTOCHECKBOX, 20, 112, 340, 26, CHECKBOX_ID
        )
        _state["status"] = _make_child(
            "STATIC", "status: clicked=0 checkbox=off", SS_LEFT, 20, 152, 360, 26, STATUS_ID
        )
        for key in ("button", "edit", "checkbox", "status"):
            if _state[key]:
                user32.SendMessageW(_state[key], WM_SETFONT, font, 1)
        return 0

    if msg == WM_COMMAND:
        ctrl_id = wparam & 0xFFFF
        code = (wparam >> 16) & 0xFFFF
        if ctrl_id == BUTTON_ID and code == BN_CLICKED:
            _state["clicks"] += 1
            _render_status()
            return 0
        if ctrl_id == CHECKBOX_ID and code == BN_CLICKED:
            checked = user32.SendMessageW(_state["checkbox"], BM_GETCHECK, 0, 0)
            _state["checked"] = bool(checked)
            _render_status()
            return 0

    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0

    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0

    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _occluder_proc(hwnd, msg, wparam, lparam):
    if msg == WM_CREATE:
        _state["occluder_hwnd"] = hwnd
        _state["occluder_status"] = user32.CreateWindowExW(
            0,
            "STATIC",
            "occluder clicks=0",
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            20,
            20,
            300,
            30,
            hwnd,
            wintypes.HMENU(2001),
            kernel32.GetModuleHandleW(None),
            None,
        )
        return 0
    if msg == WM_LBUTTONDOWN:
        _click_counts["occluder"] += 1
        user32.SetWindowTextW(
            _state["occluder_status"], f"occluder clicks={_click_counts['occluder']}"
        )
        return 0
    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_proc_ref = WNDPROC(_window_proc)
_occluder_proc_ref = WNDPROC(_occluder_proc)


def _register(window_class: str, proc) -> None:
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hbrBackground = ctypes.c_void_p(6)
    wc.lpszClassName = window_class
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())


def _message_loop() -> None:
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=int, default=220)
    parser.add_argument("--y", type=int, default=180)
    parser.add_argument("--w", type=int, default=420)
    parser.add_argument("--h", type=int, default=240)
    parser.add_argument("--auto-close-seconds", type=float, default=0)
    parser.add_argument("--occluder", action="store_true")
    parser.add_argument("--show-no-activate", action="store_true")
    args = parser.parse_args()

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass

    if args.occluder:
        _register("GUIBridgeOccluder", _occluder_proc_ref)
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST,
            "GUIBridgeOccluder",
            "GUIBridge Occluder",
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            args.x + 20,
            args.y + 20,
            args.w,
            args.h,
            None,
            None,
            kernel32.GetModuleHandleW(None),
            None,
        )
        user32.SetWindowPos(hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        print(f"OCCLUDER_HANDLE={int(hwnd)}", flush=True)
    else:
        _register(WINDOW_CLASS, _proc_ref)
        style = WS_OVERLAPPEDWINDOW
        if not args.show_no_activate:
            style |= WS_VISIBLE
        hwnd = user32.CreateWindowExW(
            0,
            WINDOW_CLASS,
            APP_TITLE,
            style,
            args.x,
            args.y,
            args.w,
            args.h,
            None,
            None,
            kernel32.GetModuleHandleW(None),
            None,
        )
        if hwnd and args.show_no_activate:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        print(f"WINDOW_HANDLE={int(hwnd)}", flush=True)
        print(f"WINDOW_TITLE={APP_TITLE}", flush=True)

    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())

    if args.auto_close_seconds > 0:
        threading.Timer(
            args.auto_close_seconds,
            lambda: user32.PostMessageW(hwnd, WM_CLOSE, 0, 0),
        ).start()

    _message_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

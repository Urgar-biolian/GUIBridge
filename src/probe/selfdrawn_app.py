"""Controlled self-drawn Win32 target for the Phase 1 capability scan.

Unlike native_test_app.py (standard BUTTON/EDIT/CHECKBOX children exposed via
the MSAA-to-UIA bridge), this window paints its own "button"/"edit"/status with
GDI in WM_PAINT and creates NO child controls. It models a custom-rendered app
(game/canvas/self-drawn UI): the UIA tree should expose only the window frame,
no Edit/Button semantic nodes, so background semantic operation is unavailable
and OCR/vision is locate-only. Controlled local target; no user-app interaction.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import threading
from ctypes import wintypes

APP_TITLE = "GUIBridge SelfDrawn Target"
WINDOW_CLASS = "GUIBridgeSelfDrawnWindow"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_LBUTTONDOWN = 0x0201
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
TRANSPARENT = 1
DT_CENTER = 0x01
DT_VCENTER = 0x04
DT_SINGLELINE = 0x20


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


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.restype = wintypes.ATOM
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

_state = {"hwnd": None, "clicks": 0}


def _paint(hwnd):
    ps = PAINTSTRUCT()
    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
    gdi32.SetBkMode(hdc, TRANSPARENT)
    gdi32.TextOutW(hdc, 20, 16, "Self-drawn UI (no child controls)", 31)
    # painted "button"
    btn = wintypes.RECT(20, 50, 170, 86)
    brush = gdi32.CreateSolidBrush(0x00D0D0D0)
    user32.FillRect(hdc, ctypes.byref(btn), brush)
    gdi32.DeleteObject(brush)
    gdi32.Rectangle(hdc, 20, 50, 170, 86)
    user32.DrawTextW(hdc, "Run action", -1, ctypes.byref(btn), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
    # painted "edit"
    gdi32.Rectangle(hdc, 20, 100, 360, 130)
    gdi32.TextOutW(hdc, 28, 106, "initial", 7)
    # painted status
    status = f"status: clicked={_state['clicks']}"
    gdi32.TextOutW(hdc, 20, 150, status, len(status))
    user32.EndPaint(hwnd, ctypes.byref(ps))


def _window_proc(hwnd, msg, wparam, lparam):
    if msg == WM_PAINT:
        _paint(hwnd)
        return 0
    if msg == WM_LBUTTONDOWN:
        _state["clicks"] += 1
        user32.InvalidateRect(hwnd, None, True)
        return 0
    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_proc_ref = WNDPROC(_window_proc)


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
    args = parser.parse_args()

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass

    wc = WNDCLASSW()
    wc.lpfnWndProc = _proc_ref
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hbrBackground = ctypes.c_void_p(6)
    wc.lpszClassName = WINDOW_CLASS
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())

    hwnd = user32.CreateWindowExW(
        0, WINDOW_CLASS, APP_TITLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        args.x, args.y, args.w, args.h, None, None, kernel32.GetModuleHandleW(None), None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    _state["hwnd"] = hwnd
    print(f"WINDOW_HANDLE={int(hwnd)}", flush=True)
    print(f"WINDOW_TITLE={APP_TITLE}", flush=True)

    if args.auto_close_seconds > 0:
        threading.Timer(args.auto_close_seconds, lambda: user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)).start()

    _message_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
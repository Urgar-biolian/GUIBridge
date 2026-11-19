"""Self-contained Win32 primitives for the WeChat foreground adapter.

Productized from the E11 demo (src/probe/experiment_wechat_send.py) and the probe
win32_helpers. Kept inside the adapter package so the formal adapter does not import
experimental probe modules. All input here is FOREGROUND physical input (SendInput /
mouse_event): it moves the real cursor and requires WeChat in the foreground, so the
adapter declares PHYSICAL_INPUT / success_with_interference and never claims background
or zero-interference operation.

Window whitelist: only WeChat's Qt main window (class Qt51514QWindowIcon, weixin.exe)
and its self-drawn render child (MMUIRenderSubWindowHW) are ever located or touched.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SW_RESTORE = 9
SW_MINIMIZE = 6
VK_CONTROL = 0x11
VK_F = 0x46
VK_V = 0x56
VK_A = 0x41
VK_RETURN = 0x0D
VK_DELETE = 0x2E
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WECHAT_MAIN_CLASS = "qt51514qwindowicon"
WECHAT_RENDER_CLASS = "mmuirendersubwindowhw"
WECHAT_IMAGES = ("weixin.exe", "wechatappex.exe")

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(int(hwnd)), ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(int(hwnd)), buf, 256)
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(int(hwnd)), ctypes.byref(pid))
    return int(pid.value)


def process_image(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def enum_top_level_windows() -> list[dict]:
    windows: list[dict] = []

    def callback(hwnd, _lparam):
        h = int(hwnd)
        windows.append({"hwnd": h, "pid": window_pid(h), "class": window_class(h),
                        "visible": bool(user32.IsWindowVisible(hwnd))})
        return True

    user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return windows


def _render_children(parent: int) -> list[dict]:
    found: list[dict] = []

    def callback(hwnd, _lparam):
        h = int(hwnd)
        if window_class(h).lower() == WECHAT_RENDER_CLASS:
            x, y, w, hh = window_rect(h)
            found.append({"hwnd": h, "parent_hwnd": parent, "rect": (x, y, w, hh), "area": w * hh})
        return True

    user32.EnumChildWindows(wintypes.HWND(int(parent)), _WNDENUMPROC(callback), 0)
    return found


def locate_wechat() -> dict | None:
    """Whitelist locate: largest MMUIRenderSubWindowHW render under a weixin.exe Qt main
    window. Returns a WindowState dict, or None if WeChat is not running / no render."""
    renders: list[dict] = []
    for w in enum_top_level_windows():
        if w["class"].lower() != WECHAT_MAIN_CLASS:
            continue
        if process_image(w["pid"]) not in WECHAT_IMAGES:
            continue
        renders.extend(_render_children(w["hwnd"]))
    if not renders:
        return None
    render = max(renders, key=lambda r: r["area"])
    rh, parent = render["hwnd"], render["parent_hwnd"]
    x, y, w, h = render["rect"]
    return {"render_hwnd": rh, "restore_hwnd": parent, "window_id": format(rh, "x"),
            "rect": (x, y, w, h), "original_fg": foreground_hwnd(),
            "on_screen": x >= -10000 and y >= -10000 and w > 1 and h > 1}


def send_key(vk: int, up: bool = False) -> None:
    item = _INPUT(type=INPUT_KEYBOARD)
    item.union.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0, time=0, dwExtraInfo=0)
    user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))


def combo(vk: int) -> None:
    send_key(VK_CONTROL)
    send_key(vk)
    send_key(vk, up=True)
    send_key(VK_CONTROL, up=True)


def click_at(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def clipboard_write(text: str) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise RuntimeError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def ensure_foreground(hwnd: int, timeout: float = 2.0) -> bool:
    hwnd = int(hwnd)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()
    attached = bool(user32.AttachThreadInput(current_thread, target_thread, True))
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if foreground_hwnd() == hwnd:
                return True
            time.sleep(0.02)
        return False
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, False)


def force_fg(target: int) -> bool:
    """Attach to BOTH the current foreground thread and the target thread before
    SetForegroundWindow; wh.ensure_foreground (target-only) fails against another
    process's foreground lock (e.g. WeChat's CEF window)."""
    target = int(target)
    fg = foreground_hwnd()
    cur = kernel32.GetCurrentThreadId()
    fg_t = user32.GetWindowThreadProcessId(fg, None)
    tg_t = user32.GetWindowThreadProcessId(target, None)
    a1 = user32.AttachThreadInput(cur, fg_t, True)
    a2 = user32.AttachThreadInput(cur, tg_t, True)
    user32.ShowWindow(target, SW_RESTORE)
    user32.BringWindowToTop(target)
    ok = user32.SetForegroundWindow(target)
    if a1:
        user32.AttachThreadInput(cur, fg_t, False)
    if a2:
        user32.AttachThreadInput(cur, tg_t, False)
    return bool(ok)


def restore_wechat(state: dict) -> bool:
    user32.ShowWindow(state["restore_hwnd"], SW_RESTORE)
    ensure_foreground(state["restore_hwnd"])
    time.sleep(1.2)
    x, y, w, h = window_rect(state["render_hwnd"])
    state["rect"] = (x, y, w, h)
    state["on_screen"] = x >= -10000 and y >= -10000 and w > 1 and h > 1
    return state["on_screen"]


def minimize_wechat(state: dict) -> dict:
    user32.ShowWindow(state["restore_hwnd"], SW_MINIMIZE)
    time.sleep(0.8)
    ofg = state.get("original_fg")
    if ofg and user32.IsWindowVisible(wintypes.HWND(int(ofg))):
        force_fg(ofg)
    time.sleep(0.3)
    return {"reminimized": True, "foreground_returned_to": foreground_hwnd()}
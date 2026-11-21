"""Hidden-desktop FULL-SCREEN capture (E14) — reusable as the agent screenshot interface.

A hidden desktop (CreateDesktopW, never SwitchDesktop'd) is NOT the active input desktop,
so it has no DWM-composed screen surface. Two worker-side methods are measured:

  bitblt : GetDC(NULL) + BitBlt the whole virtual screen. Expected to be BLACK on a
           non-active desktop (no composed surface) — measured, not assumed.
  stitch : PrintWindow every visible top-level window into a virtual-screen-sized canvas
           at its real screen rect. This reconstructs a full-desktop image from the
           windows themselves and works regardless of which desktop is active.

All functions here MUST run on the hidden-desktop worker thread (same desktop as the
target windows); cross-desktop PrintWindow/GetDC fail. Capture is read-only: it cannot
change the host's foreground or cursor. The usage-phase interface returns the PNG path +
geometry so an agent can look at the whole hidden desktop and self-correct.

Privacy: for benign targets (native_test_app) PNGs are kept under gitignored
var/experiments. For real apps with private content, callers must hash-then-delete or
redact before persisting — this module only produces the image, it does not decide retention.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import mss.tools

import experiment_hidden_desktop as e8
import win32_helpers as wh

user32 = e8.user32
gdi32 = e8.gdi32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
PW_RENDERFULLCONTENT = e8.PW_RENDERFULLCONTENT
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def virtual_screen() -> tuple[int, int, int, int]:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return vx, vy, max(vw, 1), max(vh, 1)


def _dib_to_png(mem_dc, bmp, w: int, h: int, out_path: str) -> dict:
    """Read a 32bpp top-down DIB out of mem_dc, write RGB PNG, return non-blank stats."""
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    if got == 0:
        return {"ok": False, "w": w, "h": h, "error": "GetDIBits failed"}
    raw = buf.raw
    rgb = bytearray(w * h * 3)
    rgb[0::3] = raw[2::4]
    rgb[1::3] = raw[1::4]
    rgb[2::3] = raw[0::4]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    mss.tools.to_png(bytes(rgb), (w, h), output=out_path)
    # Coarse non-blank metric on a stride sample (full-image loop would be slow).
    stride = max(1, (w * h) // 20000)
    nb = 0
    total = 0
    colors: set[int] = set()
    for i in range(0, w * h, stride):
        b, g, r = raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2]
        total += 1
        if b or g or r:
            nb += 1
        if len(colors) < 4096:
            colors.add((r << 16) | (g << 8) | b)
    return {"ok": True, "w": w, "h": h, "path": out_path,
            "nonblack_ratio": round(nb / max(total, 1), 4),
            "distinct_colors_sampled": len(colors), "sampled_pixels": total}


def _new_canvas(w: int, h: int):
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    return screen_dc, mem_dc, bmp, old


def _free_canvas(screen_dc, mem_dc, bmp, old):
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)


def capture_bitblt(out_path: str) -> dict:
    """Method A: BitBlt the whole virtual screen from GetDC(NULL). Worker-side."""
    vx, vy, vw, vh = virtual_screen()
    screen_dc, mem_dc, bmp, old = _new_canvas(vw, vh)
    ok = bool(gdi32.BitBlt(mem_dc, 0, 0, vw, vh, screen_dc, vx, vy, SRCCOPY))
    stats = _dib_to_png(mem_dc, bmp, vw, vh, out_path)
    _free_canvas(screen_dc, mem_dc, bmp, old)
    stats["method"] = "bitblt"
    stats["bitblt_return"] = ok
    stats["virtual_screen"] = [vx, vy, vw, vh]
    return stats


def _printwindow_into(hwnd: int, dst_dc, dx: int, dy: int) -> dict:
    """PrintWindow one window into a temp surface, BitBlt it onto dst_dc at (dx,dy)."""
    x, y, w, h = wh.window_rect(hwnd)
    w, h = max(w, 1), max(h, 1)
    hwnd_dc = user32.GetDC(wintypes.HWND(int(hwnd)))
    tmp_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = gdi32.SelectObject(tmp_dc, bmp)
    pw = bool(user32.PrintWindow(wintypes.HWND(int(hwnd)), tmp_dc, PW_RENDERFULLCONTENT))
    blit = bool(gdi32.BitBlt(dst_dc, dx, dy, w, h, tmp_dc, 0, 0, SRCCOPY))
    gdi32.SelectObject(tmp_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(tmp_dc)
    user32.ReleaseDC(wintypes.HWND(int(hwnd)), hwnd_dc)
    return {"hwnd": int(hwnd), "rect": [x, y, w, h], "printwindow": pw, "blit": blit}


def capture_stitch(out_path: str) -> dict:
    """Method B: reconstruct the full desktop by PrintWindow-stitching visible windows.
    Worker-side. Background stays black (a hidden desktop paints no wallpaper)."""
    vx, vy, vw, vh = virtual_screen()
    wins = [w for w in wh.enum_top_level_windows()
            if w["visible"] and wh.window_rect(w["hwnd"])[2] > 0 and wh.window_rect(w["hwnd"])[3] > 0]
    # Paint largest first so smaller windows overlay on top (approximate z-order).
    wins.sort(key=lambda w: wh.window_rect(w["hwnd"])[2] * wh.window_rect(w["hwnd"])[3], reverse=True)
    screen_dc, mem_dc, bmp, old = _new_canvas(vw, vh)
    placed = []
    for w in wins:
        x, y, ww, hh = wh.window_rect(w["hwnd"])
        placed.append(_printwindow_into(w["hwnd"], mem_dc, x - vx, y - vy))
    stats = _dib_to_png(mem_dc, bmp, vw, vh, out_path)
    _free_canvas(screen_dc, mem_dc, bmp, old)
    stats["method"] = "stitch"
    stats["virtual_screen"] = [vx, vy, vw, vh]
    stats["window_count"] = len(placed)
    stats["windows"] = placed
    return stats


def capture_full(worker, out_dir: str, prefix: str = "hidden_full") -> dict:
    """Orchestrator: run both methods on the worker, return metrics + PNG paths.
    This is the seed of the usage-phase screenshot interface for agent self-correction."""
    os.makedirs(out_dir, exist_ok=True)
    bitblt_path = os.path.join(out_dir, f"{prefix}_bitblt.png")
    stitch_path = os.path.join(out_dir, f"{prefix}_stitch.png")
    out: dict = {}
    try:
        out["bitblt"] = worker.run(lambda: capture_bitblt(bitblt_path))
    except Exception as exc:  # noqa: BLE001
        out["bitblt"] = {"ok": False, "error": repr(exc)}
    try:
        out["stitch"] = worker.run(lambda: capture_stitch(stitch_path))
    except Exception as exc:  # noqa: BLE001
        out["stitch"] = {"ok": False, "error": repr(exc)}
    out["host_foreground_during"] = int(user32.GetForegroundWindow() or 0)
    return out


def screenshot_hidden_desktop(worker, out_path: str) -> dict:
    """Usage-phase interface: ONE full-hidden-desktop PNG for agent vision self-correction.

    Uses the stitch method (whole-screen BitBlt is black on a non-active desktop, measured
    in E14). Read-only: cannot change host foreground/cursor. Returns geometry + window
    rects + PNG path so the agent can look at the whole scene and locate/verify targets.
    Retention/privacy is the caller's decision (hash-then-delete or redact for real apps).
    """
    return worker.run(lambda: capture_stitch(out_path))
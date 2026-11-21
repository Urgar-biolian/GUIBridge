"""WeChat driver: injectable seam between the adapter orchestration and Win32/OCR.

The adapter depends only on the WeChatDriver protocol so its gates, approval,
four-state classification, privacy redaction and cleanup are unit-testable with a
fake driver (no real WeChat / Win32 / OCR). Win32WeChatDriver is the live implementation
used only under explicit user authorization; it reuses the package OCR channel and the
FocusGuard monitor. Readable PNGs are grabbed OUTSIDE the repo and deleted right after OCR.
"""

from __future__ import annotations

import os
from typing import Protocol

from packages.focusguard.monitor import Win32FocusGuard
from packages.perception.ocr import OCRChannel, grab_window_png

from . import win32


class WeChatDriver(Protocol):
    def locate(self) -> dict | None: ...
    def restore(self, ws: dict) -> bool: ...
    def read_boxes(self, ws: dict, tmp_dir: str) -> list[dict]: ...
    def click_rel(self, ws: dict, rx: int, ry: int) -> None: ...
    def clipboard_write(self, text: str) -> None: ...
    def combo(self, vk: int) -> None: ...
    def key(self, vk: int, up: bool = False) -> None: ...
    def guard(self, ws: dict): ...
    def cleanup(self, ws: dict) -> dict: ...


class Win32WeChatDriver:
    """Live foreground driver. Every input is physical foreground input (PHYSICAL_INPUT)."""

    def __init__(self, ocr: OCRChannel | None = None):
        self._ocr = ocr or OCRChannel()

    def locate(self) -> dict | None:
        return win32.locate_wechat()

    def restore(self, ws: dict) -> bool:
        return win32.restore_wechat(ws)

    def read_boxes(self, ws: dict, tmp_dir: str) -> list[dict]:
        png = grab_window_png(ws["window_id"], out_dir=tmp_dir)
        try:
            return self._ocr.read_text_boxes(png)
        finally:
            try:
                os.remove(png)
            except OSError:
                pass

    def click_rel(self, ws: dict, rx: int, ry: int) -> None:
        x, y, _, _ = ws["rect"]
        win32.click_at(x + rx, y + ry)

    def clipboard_write(self, text: str) -> None:
        win32.clipboard_write(text)

    def combo(self, vk: int) -> None:
        win32.combo(vk)

    def key(self, vk: int, up: bool = False) -> None:
        win32.send_key(vk, up=up)

    def guard(self, ws: dict) -> Win32FocusGuard:
        return Win32FocusGuard(ws["render_hwnd"])

    def cleanup(self, ws: dict) -> dict:
        return win32.minimize_wechat(ws)
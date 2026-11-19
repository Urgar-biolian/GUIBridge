"""SendInput baseline operations (physical cursor/keyboard) for E3/E4."""

from __future__ import annotations

import time

import win32_helpers as wh

BUTTON_ID = 1001
EDIT_ID = 1002
CHECKBOX_ID = 1003


def _center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    x, y, w, h = rect
    return x + w // 2, y + h // 2


def click_button(window_hwnd: int) -> None:
    x, y = _center(wh.control_rect(window_hwnd, BUTTON_ID))
    wh.click_at(x, y)


def set_edit_text(window_hwnd: int, text: str) -> None:
    x, y = _center(wh.control_rect(window_hwnd, EDIT_ID))
    wh.click_at(x, y)
    time.sleep(0.05)
    wh.send_ctrl_a()
    time.sleep(0.03)
    wh.send_text(text)


def toggle_checkbox(window_hwnd: int) -> None:
    x, y = _center(wh.control_rect(window_hwnd, CHECKBOX_ID))
    wh.click_at(x, y)

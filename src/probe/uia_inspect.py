"""Read-only UIA inspection of the controlled target (Phase 1)."""

from __future__ import annotations

import json
import sys
import time

import uiautomation as auto

TITLE = "GUIBridge UIA Test Target"
CLASS = "GUIBridgeTestWindow"


def find_window(timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for window in auto.GetRootControl().GetChildren():
            try:
                if window.Name == TITLE or window.ClassName == CLASS:
                    return window
            except Exception:
                continue
        time.sleep(0.1)
    return None


def pattern_names(control) -> list[str]:
    found = []
    for label, pattern_id in (
        ("invoke", auto.PatternId.InvokePattern),
        ("value", auto.PatternId.ValuePattern),
        ("toggle", auto.PatternId.TogglePattern),
        ("text", auto.PatternId.TextPattern),
    ):
        try:
            if control.GetPattern(pattern_id):
                found.append(label)
        except Exception:
            continue
    return found


def describe(control) -> dict:
    try:
        rect = control.BoundingRectangle
        bounds = [rect.left, rect.top, rect.right, rect.bottom]
    except Exception:
        bounds = None
    return {
        "name": control.Name,
        "class": control.ClassName,
        "type": control.ControlTypeName,
        "automation_id": control.AutomationId,
        "native_hwnd": int(control.NativeWindowHandle or 0),
        "enabled": bool(control.IsEnabled),
        "bounds": bounds,
        "patterns": pattern_names(control),
    }


def main() -> int:
    window = find_window()
    if window is None:
        print("TARGET_NOT_FOUND")
        return 1
    data = describe(window)
    children = []
    try:
        for child in window.GetChildren():
            children.append(describe(child))
    except Exception as exc:
        data["children_error"] = repr(exc)
    data["children"] = children
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

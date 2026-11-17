"""UIA pattern operations against the controlled target (Phase 1)."""

from __future__ import annotations

import re
import time

import uiautomation as auto

from packages.focusguard.monitor import FocusRun, Win32FocusGuard
from packages.focusguard.outcome import ActionResult, ResultState
from packages.routing.capability import Channel, InterferenceRisk

TARGET_TITLE = "GUIBridge UIA Test Target"
TARGET_CLASS = "GUIBridgeTestWindow"
BUTTON_ID = "1001"
EDIT_ID = "1002"
CHECKBOX_ID = "1003"
STATUS_ID = "1004"


def find_window(title: str, class_name: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for window in auto.GetRootControl().GetChildren():
            try:
                if window.Name == title or window.ClassName == class_name:
                    return window
            except Exception:
                continue
        time.sleep(0.1)
    return None


def find_control(window, automation_id: str, max_depth: int = 4):
    def walk(control, depth: int):
        try:
            children = control.GetChildren()
        except Exception:
            return None
        for child in children:
            try:
                if child.AutomationId == automation_id:
                    return child
            except Exception:
                pass
            if depth < max_depth:
                found = walk(child, depth + 1)
                if found is not None:
                    return found
        return None

    return walk(window, 0)


def _pattern(control, pattern_id):
    try:
        return control.GetPattern(pattern_id)
    except Exception:
        return None


def read_status(window) -> str:
    control = find_control(window, STATUS_ID)
    return control.Name if control else ""


def read_edit(window) -> str:
    control = find_control(window, EDIT_ID)
    pattern = _pattern(control, auto.PatternId.ValuePattern) if control else None
    return pattern.Value if pattern else ""


def toggle_state(window) -> int | None:
    control = find_control(window, CHECKBOX_ID)
    pattern = _pattern(control, auto.PatternId.TogglePattern) if control else None
    return int(pattern.ToggleState) if pattern else None


def clicked_count(status: str) -> int | None:
    match = re.search(r"clicked=(\d+)", status)
    return int(match.group(1)) if match else None


def checkbox_on(status: str) -> bool | None:
    match = re.search(r"checkbox=(on|off)", status)
    if not match:
        return None
    return match.group(1) == "on"


def _run(guard: Win32FocusGuard, action) -> tuple[FocusRun, str | None]:
    try:
        return guard.wrap_with_events(action), None
    except Exception as exc:
        before = guard.snapshot()
        return FocusRun(result=None, before=before, after=guard.snapshot()), repr(exc)


def _result(
    run: FocusRun,
    verified: bool,
    evidence: dict,
    error: str | None = None,
) -> ActionResult:
    if error or not verified:
        state = ResultState.FAILED
    elif run.unexpected_focus_switch or run.cursor_displacement > 0:
        state = ResultState.SUCCESS_WITH_INTERFERENCE
    else:
        state = ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    evidence = dict(evidence)
    evidence["cursor_displacement"] = run.cursor_displacement
    evidence["foreground_events"] = [foreground for _, foreground in run.foreground_events]
    evidence["external_input_during_window"] = run.external_input_during_window
    if error:
        evidence["error"] = error
    return ActionResult(
        state=state,
        channel=Channel.UIA,
        risk=InterferenceRisk.LOGICAL_ONLY,
        effect_verified=verified,
        evidence=evidence,
        focus_before=run.before,
        focus_after=run.after,
        unexpected_focus_switch=run.unexpected_focus_switch,
    )


def invoke_button(window, guard: Win32FocusGuard) -> ActionResult:
    control = find_control(window, BUTTON_ID)
    pattern = _pattern(control, auto.PatternId.InvokePattern) if control else None
    before = read_status(window)
    if pattern is None:
        return _result(
            FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot()),
            False,
            {"status_before": before},
            error="InvokePattern unavailable",
        )
    run, error = _run(guard, lambda: pattern.Invoke())
    time.sleep(0.05)
    after = read_status(window)
    verified = clicked_count(after) is not None and after != before
    return _result(
        run,
        verified,
        {"status_before": before, "status_after": after},
        error,
    )


def set_edit(window, guard: Win32FocusGuard, value: str) -> ActionResult:
    control = find_control(window, EDIT_ID)
    pattern = _pattern(control, auto.PatternId.ValuePattern) if control else None
    before = read_edit(window)
    if pattern is None:
        return _result(
            FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot()),
            False,
            {"value_before": before},
            error="ValuePattern unavailable",
        )
    run, error = _run(guard, lambda: pattern.SetValue(value))
    time.sleep(0.05)
    after = read_edit(window)
    return _result(
        run,
        after == value,
        {"value_before": before, "value_after": after, "expected": value},
        error,
    )


def toggle_checkbox(window, guard: Win32FocusGuard) -> ActionResult:
    control = find_control(window, CHECKBOX_ID)
    pattern = _pattern(control, auto.PatternId.TogglePattern) if control else None
    before = toggle_state(window)
    if pattern is None:
        return _result(
            FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot()),
            False,
            {"toggle_before": before},
            error="TogglePattern unavailable",
        )
    run, error = _run(guard, lambda: pattern.Toggle())
    time.sleep(0.05)
    after = toggle_state(window)
    return _result(
        run,
        before is not None and after is not None and after != before,
        {"toggle_before": before, "toggle_after": after},
        error,
    )

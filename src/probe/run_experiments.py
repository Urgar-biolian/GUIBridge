"""Phase 1 experiment runner: E1-E6 with raw JSON output.

Read-only toward Trae/WeChat: no chat messages are sent. SendInput runs only
against the controlled target window and restores the cursor afterwards.
"""

from __future__ import annotations

import ctypes
import dataclasses
import datetime
import json
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uiautomation as auto  # noqa: E402

import uia_exec as ux  # noqa: E402
import win32_helpers as wh  # noqa: E402
import sendinput_ops as si  # noqa: E402
from packages.focusguard.monitor import FocusRun, Win32FocusGuard  # noqa: E402
from packages.focusguard.outcome import ResultState  # noqa: E402
from packages.routing.capability import Channel, InterferenceRisk  # noqa: E402

PROBE_DIR = Path(__file__).parent
APP = PROBE_DIR / "native_test_app.py"
RUNS = ROOT / "var" / "experiments"
TARGET_TITLE = ux.TARGET_TITLE
TARGET_CLASS = ux.TARGET_CLASS
OCCLUDER_TITLE = "GUIBridge Occluder"
OCCLUDER_CLASS = "GUIBridgeOccluder"


def jsonable(value):
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def start_app(*, occluder: bool = False, x: int = 220, y: int = 180, w: int = 420, h: int = 240, auto_close: int = 240, no_activate: bool = False):
    args = [
        sys.executable,
        str(APP),
        "--x",
        str(x),
        "--y",
        str(y),
        "--w",
        str(w),
        "--h",
        str(h),
        "--auto-close-seconds",
        str(auto_close),
    ]
    if occluder:
        args.append("--occluder")
    if no_activate:
        args.append("--show-no-activate")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_app_with_handle(*, x: int = 660, y: int = 260, w: int = 420, h: int = 240, auto_close: int = 120):
    args = [
        sys.executable,
        str(APP),
        "--x",
        str(x),
        "--y",
        str(y),
        "--w",
        str(w),
        "--h",
        str(h),
        "--auto-close-seconds",
        str(auto_close),
        "--show-no-activate",
    ]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    lines: list[str] = []
    reader = threading.Thread(
        target=lambda: lines.append(proc.stdout.readline()),
        daemon=True,
    )
    reader.start()
    reader.join(10)
    if not lines or "WINDOW_HANDLE=" not in lines[0]:
        proc.terminate()
        raise RuntimeError(f"target window handle not reported: {lines!r}")
    return proc, int(lines[0].split("=", 1)[1])


def process_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return name.lower() in (result.stdout or "").lower()
    except Exception:
        return False


def _classify(run: FocusRun, verified: bool, error: str | None, channel: Channel) -> ResultState:
    from packages.focusguard.classify import classify

    return classify(run, verified, error, channel)


def action_record(run: FocusRun, verified: bool, evidence: dict, error: str | None = None, channel: Channel = Channel.UIA, risk: InterferenceRisk = InterferenceRisk.LOGICAL_ONLY):
    state = _classify(run, verified, error, channel)
    evidence = dict(evidence)
    evidence["cursor_displacement"] = run.cursor_displacement
    evidence["external_input_during_window"] = run.external_input_during_window
    evidence["hook_foreground_events"] = [foreground for _, foreground in run.hook_foreground_events]
    evidence["event_hook_active"] = run.event_hook_active
    if channel is Channel.FOREGROUND_INPUT:
        evidence["input_injected_by_action"] = True
    if error:
        evidence["error"] = error
    return {
        "state": state.value,
        "channel": channel.value,
        "risk": risk.value,
        "effect_verified": verified,
        "evidence": evidence,
        "cursor_displacement": run.cursor_displacement,
        "foreground_events": [foreground for _, foreground in run.foreground_events],
        "unexpected_focus_switch": run.unexpected_focus_switch,
        "external_input_during_window": run.external_input_during_window,
        "focus_before": jsonable(run.before),
        "focus_after": jsonable(run.after),
    }


def safe_action(guard: Win32FocusGuard, action):
    try:
        return guard.wrap_with_events(action), None
    except Exception as exc:
        before = guard.snapshot()
        return FocusRun(result=None, before=before, after=guard.snapshot()), repr(exc)


def experiment_e1(window, guard: Win32FocusGuard) -> dict:
    status_initial = ux.read_status(window)
    clicked_initial = ux.clicked_count(status_initial)
    toggle = ux.toggle_checkbox(window, guard)
    status_after_toggle = ux.read_status(window)
    toggle_back = ux.toggle_checkbox(window, guard)
    button = ux.invoke_button(window, guard)
    status_after_button = ux.read_status(window)
    clicked_after = ux.clicked_count(status_after_button)
    edit = ux.set_edit(window, guard, "uia-value")
    return {
        "toggle": jsonable(toggle),
        "toggle_back": jsonable(toggle_back),
        "button": jsonable(button),
        "edit": jsonable(edit),
        "observed": {
            "status_initial": status_initial,
            "clicked_initial": clicked_initial,
            "status_after_toggle": status_after_toggle,
            "checkbox_on_after_toggle": ux.checkbox_on(status_after_toggle),
            "status_after_button": status_after_button,
            "clicked_after": clicked_after,
            "edit_value_after": ux.read_edit(window),
        },
    }


def experiment_e1_background(trials: int = 3) -> dict:
    tests = {
        "invoke": lambda window, guard: ux.invoke_button(window, guard),
        "value": lambda window, guard: ux.set_edit(window, guard, "bg-value"),
        "toggle": lambda window, guard: ux.toggle_checkbox(window, guard),
    }
    output = {}
    for name, action in tests.items():
        procs = []
        windows = []
        runs = []
        try:
            for index in range(trials):
                proc, hwnd = start_app_with_handle(x=660 + index * 12, y=260 + index * 12)
                procs.append(proc)
                windows.append((hwnd, auto.ControlFromHandle(hwnd)))
            time.sleep(1.2)
            for hwnd, window in windows:
                quiet = wh.wait_for_quiescence()
                foreground = int(wh.user32.GetForegroundWindow() or 0)
                guard = Win32FocusGuard(hwnd)
                result = action(window, guard)
                runs.append(
                    {
                        "target_hwnd": hwnd,
                        "foreground_at_start": foreground,
                        "started_in_background": foreground != hwnd,
                        "quiescent_before_action": quiet,
                        "result": jsonable(result),
                    }
                )
        finally:
            for proc in procs:
                proc.terminate()
        output[name] = runs
    return output


def experiment_e1_foreground(trials: int = 3) -> dict:
    tests = {
        "invoke": lambda window, guard: ux.invoke_button(window, guard),
        "value": lambda window, guard: ux.set_edit(window, guard, "fg-value"),
        "toggle": lambda window, guard: ux.toggle_checkbox(window, guard),
    }
    output = {}
    for name, action in tests.items():
        procs = []
        windows = []
        runs = []
        try:
            for index in range(trials):
                proc, hwnd = start_app_with_handle(x=660 + index * 12, y=520 + index * 12)
                procs.append(proc)
                windows.append((hwnd, auto.ControlFromHandle(hwnd)))
            time.sleep(1.2)
            for hwnd, window in windows:
                activated = wh.ensure_foreground(hwnd)
                quiet = wh.wait_for_quiescence()
                foreground = int(wh.user32.GetForegroundWindow() or 0)
                guard = Win32FocusGuard(hwnd)
                result = action(window, guard)
                runs.append(
                    {
                        "target_hwnd": hwnd,
                        "foreground_at_start": foreground,
                        "started_in_background": foreground != hwnd,
                        "activated_before_action": activated,
                        "quiescent_before_action": quiet,
                        "result": jsonable(result),
                    }
                )
        finally:
            for proc in procs:
                proc.terminate()
        output[name] = runs
    return output


def process_pids(name: str) -> list[int]:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        pids = []
        for line in (result.stdout or "").splitlines():
            parts = [part.strip('"') for part in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == name.lower():
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    continue
        return pids
    except Exception:
        return []


def scan_windows_by_process(name: str) -> dict:
    pids = process_pids(name)
    windows = [window for window in wh.enum_top_level_windows() if window["pid"] in pids]
    visible = [window for window in windows if window["visible"]]
    uia = []
    for window in visible[:5]:
        try:
            control = auto.ControlFromHandle(window["hwnd"])
            nodes = []
            types = {}

            def walk(ctrl, depth):
                if len(nodes) >= 400 or depth > 5:
                    return
                try:
                    nodes.append(ctrl.ControlTypeName)
                    types[ctrl.ControlTypeName] = types.get(ctrl.ControlTypeName, 0) + 1
                    for child in ctrl.GetChildren():
                        walk(child, depth + 1)
                except Exception:
                    return

            walk(control, 0)
            uia.append(
                {
                    "hwnd": window["hwnd"],
                    "title": window["title"],
                    "class": window["class"],
                    "node_count": len(nodes),
                    "types": types,
                    "has_edit": "EditControl" in types,
                    "has_button": "ButtonControl" in types,
                }
            )
        except Exception as exc:
            uia.append({"hwnd": window["hwnd"], "error": repr(exc)})
    return {
        "process_running": bool(pids),
        "pids": pids,
        "window_count": len(windows),
        "visible_window_count": len(visible),
        "windows": windows[:20],
        "uia_visible_windows": uia,
        "note": "read-only EnumWindows + PID match; no messages sent" if windows else "no top-level window matched process PID",
    }


def experiment_e2(target_hwnd: int, guard: Win32FocusGuard) -> dict:
    tx, ty, tw, th = wh.window_rect(target_hwnd)
    screen_w = int(wh.user32.GetSystemMetrics(0))
    ox = min(tx + tw + 80, max(0, screen_w - 340))
    occluder_proc = start_app(occluder=True, x=ox, y=ty, w=300, h=200, auto_close=120)
    try:
        occluder = ux.find_window(OCCLUDER_TITLE, OCCLUDER_CLASS, timeout=8)
        if occluder is None:
            return {"error": "occluder window not found"}
        occluder_hwnd = int(occluder.NativeWindowHandle)
        positives = []
        dwell_curve = []
        for dwell in (0.02, 0.05, 0.12):
            bucket = []
            for _ in range(3):
                wh.ensure_foreground(target_hwnd)
                time.sleep(0.1)

                def disturb():
                    wh.quick_foreground(occluder_hwnd)
                    time.sleep(dwell)
                    wh.quick_foreground(target_hwnd)
                    time.sleep(0.05)

                run, error = safe_action(guard, disturb)
                poll_hit = any(fg == occluder_hwnd for _, fg in run.foreground_events)
                hook_hit = any(fg == occluder_hwnd for _, fg in run.hook_foreground_events)
                combined = sorted(run.foreground_events + run.hook_foreground_events)
                occ_ts = next((ts for ts, fg in combined if fg == occluder_hwnd), None)
                tgt_ts = next((ts for ts, fg in combined if fg == target_hwnd and occ_ts is not None and ts > occ_ts), None)
                actual_dwell_ms = round((tgt_ts - occ_ts) * 1000, 1) if occ_ts is not None and tgt_ts is not None else None
                record = {
                    "requested_dwell_ms": dwell * 1000,
                    "actual_dwell_ms": actual_dwell_ms,
                    "poll_detected": poll_hit,
                    "hook_detected": hook_hit,
                    "detected": poll_hit or hook_hit,
                    "poll_events": [fg for _, fg in run.foreground_events],
                    "hook_events": [fg for _, fg in run.hook_foreground_events],
                    "event_hook_active": run.event_hook_active,
                    "start_foreground": run.before.foreground_hwnd,
                    "target_restored": run.after.foreground_hwnd == target_hwnd,
                    "error": error,
                }
                bucket.append(record)
                positives.append(record)
            dwell_curve.append(
                {
                    "requested_dwell_ms": dwell * 1000,
                    "trials": len(bucket),
                    "poll_detected": sum(1 for item in bucket if item["poll_detected"]),
                    "hook_detected": sum(1 for item in bucket if item["hook_detected"]),
                    "any_detected": sum(1 for item in bucket if item["detected"]),
                    "actual_dwell_ms": [item["actual_dwell_ms"] for item in bucket],
                }
            )
        negatives = []
        for _ in range(3):
            run, error = safe_action(guard, lambda: time.sleep(0.25))
            negatives.append(
                {
                    "unexpected": run.unexpected_focus_switch,
                    "events": [fg for _, fg in run.foreground_events],
                    "hook_events": [fg for _, fg in run.hook_foreground_events],
                    "error": error,
                }
            )
        return {
            "occluder_hwnd": occluder_hwnd,
            "positives": positives,
            "negatives": negatives,
            "dwell_curve": dwell_curve,
            "detected_rate": sum(1 for item in positives if item["detected"]) / len(positives),
            "poll_detected_rate": sum(1 for item in positives if item["poll_detected"]) / len(positives),
            "hook_detected_rate": sum(1 for item in positives if item["hook_detected"]) / len(positives),
            "false_positive_rate": sum(1 for item in negatives if item["unexpected"]) / len(negatives),
        }
    finally:
        occluder_proc.terminate()


def experiment_e3(window, guard: Win32FocusGuard, target_hwnd: int) -> dict:
    original_cursor = wh.cursor_pos()
    foreground_before = int(wh.user32.GetForegroundWindow() or 0)
    activated = wh.ensure_foreground(target_hwnd)
    results = {"activated": activated, "foreground_before_experiment": foreground_before}

    status_before = ux.read_status(window)
    count_before = ux.clicked_count(status_before)
    run, error = safe_action(guard, lambda: si.click_button(target_hwnd))
    status_after = ux.read_status(window)
    count_after = ux.clicked_count(status_after)
    results["button"] = action_record(
        run,
        count_before is not None and count_after == count_before + 1,
        {"status_before": status_before, "status_after": status_after},
        error,
        channel=Channel.FOREGROUND_INPUT,
        risk=InterferenceRisk.PHYSICAL_INPUT,
    )

    value_before = ux.read_edit(window)
    run, error = safe_action(guard, lambda: si.set_edit_text(target_hwnd, "sendinput-value"))
    value_after = ux.read_edit(window)
    results["edit"] = action_record(
        run,
        value_after == "sendinput-value",
        {"value_before": value_before, "value_after": value_after},
        error,
        channel=Channel.FOREGROUND_INPUT,
        risk=InterferenceRisk.PHYSICAL_INPUT,
    )

    toggle_before = ux.toggle_state(window)
    run, error = safe_action(guard, lambda: si.toggle_checkbox(target_hwnd))
    toggle_after = ux.toggle_state(window)
    results["checkbox"] = action_record(
        run,
        toggle_before is not None and toggle_after is not None and toggle_after != toggle_before,
        {"toggle_before": toggle_before, "toggle_after": toggle_after},
        error,
        channel=Channel.FOREGROUND_INPUT,
        risk=InterferenceRisk.PHYSICAL_INPUT,
    )

    wh.user32.SetCursorPos(int(original_cursor[0]), int(original_cursor[1]))
    results["cursor_restored_to"] = original_cursor
    return results


def experiment_e4(window, guard: Win32FocusGuard, target_hwnd: int, neutral_hwnd: int) -> dict:
    tx, ty, tw, th = wh.window_rect(target_hwnd)
    results = {"original_rect": [tx, ty, tw, th]}

    wh.move_window(target_hwnd, tx + 120, ty + 60, tw + 40, th + 20)
    time.sleep(0.3)
    moved_rect = wh.window_rect(target_hwnd)
    results["moved_rect"] = list(moved_rect)
    results["neutral_activated"] = (
        wh.ensure_foreground(neutral_hwnd) if neutral_hwnd else False
    )
    time.sleep(0.2)
    status_before = ux.read_status(window)
    count_before = ux.clicked_count(status_before)
    uia_result = ux.invoke_button(window, guard)
    status_after = ux.read_status(window)
    count_after = ux.clicked_count(status_after)
    results["move_uia"] = {
        "result": jsonable(uia_result),
        "count_before": count_before,
        "count_after": count_after,
        "verified": count_before is not None and count_after == count_before + 1,
    }

    wh.ensure_foreground(target_hwnd)
    status_before = ux.read_status(window)
    count_before = ux.clicked_count(status_before)
    run, error = safe_action(guard, lambda: si.click_button(target_hwnd))
    status_after = ux.read_status(window)
    count_after = ux.clicked_count(status_after)
    results["move_sendinput"] = action_record(
        run,
        count_before is not None and count_after == count_before + 1,
        {"status_before": status_before, "status_after": status_after},
        error,
        channel=Channel.FOREGROUND_INPUT,
        risk=InterferenceRisk.PHYSICAL_INPUT,
    )

    wh.move_window(target_hwnd, tx, ty, tw, th)
    time.sleep(0.2)

    occluder_proc = start_app(occluder=True, x=tx - 20, y=ty - 20, w=tw + 40, h=th + 40, auto_close=90)
    try:
        occluder = ux.find_window(OCCLUDER_TITLE, OCCLUDER_CLASS, timeout=8)
        if occluder is None:
            results["occlusion"] = {"error": "occluder window not found"}
        else:
            occ_hwnd = int(occluder.NativeWindowHandle)
            occ_control = ux.find_control(occluder, "2001")
            occ_before = occ_control.Name if occ_control else ""
            target_before = ux.read_status(window)
            target_count_before = ux.clicked_count(target_before)
            uia_result = ux.invoke_button(window, guard)
            target_after_uia = ux.read_status(window)
            target_count_after_uia = ux.clicked_count(target_after_uia)
            bx, by, bw, bh = wh.control_rect(target_hwnd, 1001)
            wh.click_at(bx + bw // 2, by + bh // 2)
            time.sleep(0.15)
            target_after_click = ux.read_status(window)
            target_count_after_click = ux.clicked_count(target_after_click)
            occ_control_after = ux.find_control(occluder, "2001")
            occ_after = occ_control_after.Name if occ_control_after else ""
            occ_before_count = int(re.search(r"clicks=(\d+)", occ_before).group(1)) if re.search(r"clicks=(\d+)", occ_before) else None
            occ_after_count = int(re.search(r"clicks=(\d+)", occ_after).group(1)) if re.search(r"clicks=(\d+)", occ_after) else None
            results["occlusion"] = {
                "occluder_hwnd": occ_hwnd,
                "uia_invoke": {
                    "result": jsonable(uia_result),
                    "target_count_before": target_count_before,
                    "target_count_after": target_count_after_uia,
                    "verified": target_count_before is not None and target_count_after_uia == target_count_before + 1,
                },
                "sendinput_click": {
                    "target_count_before": target_count_after_uia,
                    "target_count_after": target_count_after_click,
                    "occluder_before": occ_before_count,
                    "occluder_after": occ_after_count,
                    "target_unchanged": target_count_after_click == target_count_after_uia,
                    "occluder_received_click": occ_before_count is not None and occ_after_count == occ_before_count + 1,
                },
            }
    finally:
        occluder_proc.terminate()

    results["dpi_test"] = {
        "status": "not_executed",
        "reason": "changing monitor DPI would disrupt the user session",
    }
    return results


def experiment_e5(window) -> dict:
    native = {
        "app": "GUIBridge UIA Test Target",
        "class": TARGET_CLASS,
        "uia_patterns": {
            "button": "invoke",
            "edit": "value",
            "checkbox": "toggle",
            "status": "text/name",
        },
        "channels": {"uia": True, "foreground_input": True},
        "risk": {"uia": "focus_switch", "foreground_input": "physical_input"},
        "risk_note": "UIA risk measured in E1b: background pattern calls switched foreground with cursor displacement 0",
    }
    trae_running = process_running("Trae.exe")
    trae = {"process_running": trae_running}
    if trae_running:
        try:
            probe = subprocess.run(
                [sys.executable, str(PROBE_DIR / "uia_probe.py")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            dump_path = PROBE_DIR / "uia_dump.json"
            nodes = json.loads(dump_path.read_text(encoding="utf-8")) if dump_path.exists() else []
            text = json.dumps(nodes, ensure_ascii=False).lower()
            trae.update(
                {
                    "probe_exit": probe.returncode,
                    "uia_node_count": len(nodes),
                    "has_chat_composer": "chat-input" in text or "composer" in text,
                    "has_send_button": "send-button" in text or "send_button" in text,
                    "stdout_tail": (probe.stdout or "")[-600:],
                }
            )
        except Exception as exc:
            trae["probe_error"] = repr(exc)
    else:
        trae["note"] = "Trae not running; UIA probe not executed"

    wechat_running = process_running("Weixin.exe")
    wechat = {"process_running": wechat_running}
    if wechat_running:
        try:
            wechat.update(scan_windows_by_process("Weixin.exe"))
        except Exception as exc:
            wechat["scan_error"] = repr(exc)
    else:
        wechat["note"] = "WeChat not running; prior negative evidence in src/probe/PROBE_REPORT.md"

    return {"native": native, "trae": trae, "wechat": wechat}


def experiment_e6() -> dict:
    cdp = {"port": 9222, "open": False}
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2) as response:
            targets = json.loads(response.read().decode("utf-8", errors="replace"))
        cdp["open"] = True
        cdp["targets"] = [
            {"type": item.get("type"), "title": item.get("title"), "url": item.get("url")}
            for item in targets[:10]
        ]
    except Exception as exc:
        cdp["error"] = repr(exc)
    return {
        "trae_process": process_running("Trae.exe"),
        "cdp": cdp,
        "messages_sent": 0,
        "note": "read-only; no chat messages sent",
    }


def collect_env() -> dict:
    try:
        import importlib.metadata as metadata

        uia_version = metadata.version("uiautomation")
    except Exception:
        uia_version = "unknown"
    try:
        dpi = int(wh.user32.GetDpiForSystem())
    except Exception:
        dpi = None
    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "uiautomation": uia_version,
        "screen": [int(wh.user32.GetSystemMetrics(0)), int(wh.user32.GetSystemMetrics(1))],
        "dpi": dpi,
        "git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
    }


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"run_id": run_id, "env": collect_env(), "experiments": {}}

    target_proc = start_app(auto_close=600, no_activate=True)
    try:
        window = ux.find_window(TARGET_TITLE, TARGET_CLASS, timeout=10)
        if window is None:
            raise RuntimeError("target window not found")
        target_hwnd = int(window.NativeWindowHandle)
        guard = Win32FocusGuard(target_hwnd)
        results["target"] = {
            "hwnd": target_hwnd,
            "title": window.Name,
            "class": window.ClassName,
        }

        time.sleep(0.8)
        neutral_hwnd = wh.find_neutral_window({target_hwnd})
        baseline_activated = wh.ensure_foreground(neutral_hwnd) if neutral_hwnd else False
        time.sleep(0.2)
        results["baseline"] = {
            "neutral_hwnd": neutral_hwnd,
            "activated": baseline_activated,
            "foreground": int(wh.user32.GetForegroundWindow() or 0),
        }

        steps = [
            ("E1", lambda: experiment_e1(window, guard)),
            ("E1b", lambda: experiment_e1_background()),
            ("E1c", lambda: experiment_e1_foreground()),
            ("E2", lambda: experiment_e2(target_hwnd, guard)),
            ("E3", lambda: experiment_e3(window, guard, target_hwnd)),
            ("E4", lambda: experiment_e4(window, guard, target_hwnd, neutral_hwnd)),
            ("E5", lambda: experiment_e5(window)),
            ("E6", experiment_e6),
        ]
        for name, step in steps:
            try:
                results["experiments"][name] = step()
            except Exception as exc:
                results["experiments"][name] = {
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
    finally:
        target_proc.terminate()

    output = run_dir / "results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "run_id": run_id,
        "output": str(output),
        "e1_states": {
            key: results["experiments"].get("E1", {}).get(key, {}).get("state")
            for key in ("button", "edit", "toggle", "toggle_back")
        },
        "e2": {
            "detected_rate": results["experiments"].get("E2", {}).get("detected_rate"),
            "poll_detected_rate": results["experiments"].get("E2", {}).get("poll_detected_rate"),
            "hook_detected_rate": results["experiments"].get("E2", {}).get("hook_detected_rate"),
            "false_positive_rate": results["experiments"].get("E2", {}).get("false_positive_rate"),
            "dwell_curve": results["experiments"].get("E2", {}).get("dwell_curve"),
        },
        "e1c": {
            name: {
                "foreground_trials": sum(1 for run in runs if not run["started_in_background"]),
                "trials": len(runs),
                "states": [run["result"]["state"] for run in runs],
                "cursor_displacement": [run["result"]["evidence"].get("cursor_displacement") for run in runs],
            }
            for name, runs in results["experiments"].get("E1c", {}).items()
        },
        "e1b": {
            name: {
                "background_trials": sum(1 for run in runs if run["started_in_background"]),
                "trials": len(runs),
                "states": [run["result"]["state"] for run in runs],
                "cursor_displacement": [run["result"]["evidence"].get("cursor_displacement") for run in runs],
            }
            for name, runs in results["experiments"].get("E1b", {}).items()
        },
        "e3_states": {
            key: results["experiments"].get("E3", {}).get(key, {}).get("state")
            for key in ("button", "edit", "checkbox")
        },
        "e4_move_uia": results["experiments"].get("E4", {}).get("move_uia", {}).get("verified"),
        "e4_occlusion": results["experiments"].get("E4", {}).get("occlusion", {}),
        "errors": {
            name: data.get("error")
            for name, data in results["experiments"].items()
            if isinstance(data, dict) and data.get("error")
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

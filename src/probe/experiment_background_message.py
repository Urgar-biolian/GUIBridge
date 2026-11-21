"""E7 runner: background window-message input across two controlled app models.

Measures PostMessage/SendMessage (provisional "background_message" channel) against a
standard-control Win32 app and a self-drawn app, both kept in the BACKGROUND while a
neutral window holds the foreground. Includes a UIA Invoke comparison on the same
native target. Raw JSON -> var/experiments/<run_id>/background_message.json (gitignored).

Controlled local targets only. No real-app writes, no Trae/WeChat interaction, no
SendInput here (foreground baselines live in run_experiments E1/E3).
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE_DIR = Path(__file__).parent
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import uiautomation as auto  # noqa: E402

import postmessage_ops as pm  # noqa: E402
import uia_exec as ux  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

NATIVE_APP = PROBE_DIR / "native_test_app.py"
SELFDRAWN_APP = PROBE_DIR / "selfdrawn_app.py"
RUNS = ROOT / "var" / "experiments"
SELFDRAWN_CLASS = "GUIBridgeSelfDrawnWindow"


def _launch(script: Path, extra: list[str], x: int, y: int) -> tuple[subprocess.Popen, int]:
    args = [sys.executable, str(script), "--x", str(x), "--y", str(y),
            "--w", "420", "--h", "240", "--auto-close-seconds", "180", *extra]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8")
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(10)
    if not lines or "WINDOW_HANDLE=" not in lines[0]:
        proc.terminate()
        raise RuntimeError(f"window handle not reported by {script.name}: {lines!r}")
    return proc, int(lines[0].split("=", 1)[1])


def _background(hwnd: int, neutral: int) -> dict:
    wh.ensure_foreground(neutral)
    time.sleep(0.2)
    quiet = wh.wait_for_quiescence()
    fg = int(wh.user32.GetForegroundWindow() or 0)
    return {"target_hwnd": hwnd, "neutral_hwnd": neutral, "foreground_at_start": fg,
            "started_in_background": fg != hwnd, "quiescent_before_action": quiet}


def native_matrix(trials: int = 2) -> dict:
    ops = {
        "bm_click_button": lambda h, g: pm.bm_click_button(h, g),
        "raw_click_button": lambda h, g: pm.raw_click_button(h, g),
        "settext_edit": lambda h, g: pm.settext_edit(h, g, "bg-settext"),
        "char_edit": lambda h, g: pm.char_edit(h, g, "bg-char"),
        "bm_click_checkbox": lambda h, g: pm.bm_click_checkbox(h, g),
        "uia_invoke_button": lambda h, g: _uia_invoke(h, g),
    }
    out: dict = {}
    for name, op in ops.items():
        runs = []
        for index in range(trials):
            proc, hwnd = _launch(NATIVE_APP, ["--show-no-activate"], 660 + index * 12, 260 + index * 12)
            try:
                time.sleep(1.0)
                neutral = wh.find_neutral_window({hwnd})
                ctx = _background(hwnd, neutral)
                guard = Win32FocusGuard(hwnd)
                result = op(hwnd, guard)
                runs.append({**ctx, "result": result})
            finally:
                proc.terminate()
        out[name] = runs
    return out


def _uia_invoke(hwnd: int, guard: Win32FocusGuard) -> dict:
    window = auto.ControlFromHandle(hwnd)
    result = ux.invoke_button(window, guard)
    return {
        "state": result.state.value,
        "channel": result.channel.value,
        "risk": result.risk.value,
        "effect_verified": result.effect_verified,
        "evidence": {
            "cursor_displacement": result.evidence.get("cursor_displacement"),
            "unexpected_focus_switch": result.unexpected_focus_switch,
            "foreground_events": result.evidence.get("foreground_events"),
            "hook_foreground_events": result.evidence.get("hook_foreground_events"),
            "status_before": result.evidence.get("status_before"),
            "status_after": result.evidence.get("status_after"),
        },
    }


def selfdrawn_matrix(trials: int = 2) -> dict:
    runs = []
    for index in range(trials):
        proc, hwnd = _launch(SELFDRAWN_APP, ["--title-status", "--show-no-activate"], 660 + index * 12, 540 + index * 12)
        try:
            time.sleep(1.0)
            neutral = wh.find_neutral_window({hwnd})
            ctx = _background(hwnd, neutral)
            guard = Win32FocusGuard(hwnd)
            result = pm.selfdrawn_raw_click(hwnd, guard, lambda: wh.window_title(hwnd))
            runs.append({**ctx, "result": result})
        finally:
            proc.terminate()
    return {"selfdrawn_raw_click": runs}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"run_id": run_id, "experiments": {}}
    try:
        results["experiments"]["E7_native"] = native_matrix()
        results["experiments"]["E7_selfdrawn"] = selfdrawn_matrix()
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()

    output = run_dir / "background_message.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def summarize(group: dict) -> dict:
        return {
            name: {
                "trials": len(runs),
                "background_trials": sum(1 for r in runs if r["started_in_background"]),
                "states": [r["result"]["state"] for r in runs],
                "verified": [r["result"]["effect_verified"] for r in runs],
                "cursor_displacement": [r["result"]["evidence"].get("cursor_displacement") for r in runs],
                "focus_switch": [r["result"]["evidence"].get("unexpected_focus_switch") for r in runs],
            }
            for name, runs in group.items()
        }

    summary = {
        "run_id": run_id,
        "output": str(output),
        "native": summarize(results["experiments"].get("E7_native", {})),
        "selfdrawn": summarize(results["experiments"].get("E7_selfdrawn", {})),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
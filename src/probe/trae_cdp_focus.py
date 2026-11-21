"""Measure focus interference of READ-ONLY Trae CDP access (no messages sent).

Wraps a read-only Runtime.evaluate (cdp_readonly_eval.mjs) in Win32FocusGuard to
measure whether CDP logical access switches foreground or moves the cursor. This
covers the read interfaces (get_task_status / read_task_result); send_task's send
click is NOT exercised here and its risk stays unknown pending authorized live
measurement. Writes var/experiments/<run_id>/trae_cdp_focus.json.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import run_experiments as rx  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

PROBE_DIR = Path(__file__).parent
EVAL_SCRIPT = PROBE_DIR / "cdp_readonly_eval.mjs"
TRIALS = 5


def find_trae_hwnd() -> int | None:
    pids = set(rx.process_pids("Trae.exe")) | set(rx.process_pids("Trae CN.exe"))
    candidates = [
        w for w in wh.enum_top_level_windows()
        if w["visible"] and w["pid"] in pids and "trae" in w["title"].lower()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda w: len(w["title"]), reverse=True)
    return int(candidates[0]["hwnd"])


def main() -> int:
    node = shutil.which("node")
    if node is None:
        print("ABORT: node not found")
        return 2
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    trae_hwnd = find_trae_hwnd()
    if trae_hwnd is None:
        print("ABORT: Trae top-level window not found")
        return 2
    guard = Win32FocusGuard(trae_hwnd)
    print(f"trae_hwnd={trae_hwnd} title={wh.window_title(trae_hwnd)!r}")

    trials = []
    for i in range(TRIALS):
        wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)

        def read_only_cdp():
            proc = subprocess.run(
                [node, str(EVAL_SCRIPT)], capture_output=True, text=True, timeout=20
            )
            return proc.stdout.strip()

        run = guard.wrap_with_events(read_only_cdp)
        try:
            payload = json.loads(run.result) if run.result else {}
        except json.JSONDecodeError:
            payload = {"ok": False, "raw": run.result}
        record = {
            "trial": i,
            "cdp_ok": bool(payload.get("ok")),
            "cdp_value": payload.get("value"),
            "trae_foreground_at_start": run.before.target_active,
            "cursor_displacement": run.cursor_displacement,
            "unexpected_focus_switch": run.unexpected_focus_switch,
            "external_input_during_window": run.external_input_during_window,
            "event_hook_active": run.event_hook_active,
            "poll_events": [fg for _, fg in run.foreground_events],
            "hook_events": [fg for _, fg in run.hook_foreground_events],
        }
        trials.append(record)
        print(
            f"trial {i}: cdp_ok={record['cdp_ok']} cursor={record['cursor_displacement']} "
            f"focus_switch={record['unexpected_focus_switch']} ext={record['external_input_during_window']}"
        )
        time.sleep(0.3)

    clean = [t for t in trials if t["cdp_ok"] and not t["external_input_during_window"]]
    no_interference = [
        t for t in clean if not t["unexpected_focus_switch"] and t["cursor_displacement"] == 0
    ]
    result = {
        "run_id": run_id,
        "env": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
            ).stdout.strip(),
        },
        "trae_hwnd": trae_hwnd,
        "action": "read-only Runtime.evaluate (document.title + chat innerText length); no clicks/input/messages",
        "interfaces_covered": ["get_task_status", "read_task_result"],
        "interfaces_not_covered": ["send_task (send click requires authorized live measurement)"],
        "trials": trials,
        "clean_trials": len(clean),
        "no_interference_trials": len(no_interference),
        "measured_read_risk": "none" if clean and len(no_interference) == len(clean) else "unknown",
    }
    (out_dir / "trae_cdp_focus.json").write_text(
        json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"WROTE {out_dir / 'trae_cdp_focus.json'}")
    print(f"clean={len(clean)}/{TRIALS} no_interference={len(no_interference)} measured_read_risk={result['measured_read_risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
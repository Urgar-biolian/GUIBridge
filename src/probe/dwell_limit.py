"""Focused probe: quantify FocusGuard detection limit for short foreground dwells.

Phase 1 E2 could not reach dwells below ~57 ms because quick_foreground pays
ShowWindow/BringWindowToTop/attach overhead on every call. This probe uses a
faster injection (thread input attached once, bare SetForegroundWindow) and
sweeps requested dwells from 0 ms upward, recording poll vs hook detection and
the actual dwell measured from event timestamps. It writes
var/experiments/<run_id>/dwell_limit.json. Only the controlled native target and
occluder windows are touched; no chat messages, no user-app interaction.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import uia_exec as ux  # noqa: E402
import run_experiments as rx  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

ASFW_ANY = 0xFFFFFFFF
wh.user32.AllowSetForegroundWindow.argtypes = [wh.wintypes.DWORD]
wh.user32.AllowSetForegroundWindow.restype = wh.wintypes.BOOL

DWELLS = (0.0, 0.005, 0.01, 0.02, 0.05)
TRIALS = 5


def bare_foreground(hwnd: int) -> int:
    wh.user32.SetForegroundWindow(wh.wintypes.HWND(int(hwnd)))
    return int(wh.user32.GetForegroundWindow() or 0)


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    target_proc = rx.start_app(x=220, y=180, auto_close=180)
    occ_proc = rx.start_app(occluder=True, x=760, y=180, w=300, h=200, auto_close=180)
    target = occ = None
    attached = []
    current_thread = int(wh.kernel32.GetCurrentThreadId())
    try:
        target = ux.find_window(rx.TARGET_TITLE, rx.TARGET_CLASS, timeout=8)
        occ = ux.find_window(rx.OCCLUDER_TITLE, rx.OCCLUDER_CLASS, timeout=8)
        if target is None or occ is None:
            print("ABORT: target/occluder window not found")
            return 2
        target_hwnd = int(target.NativeWindowHandle)
        occ_hwnd = int(occ.NativeWindowHandle)
        guard = Win32FocusGuard(target_hwnd)

        wh.ensure_foreground(target_hwnd)
        time.sleep(0.5)
        wh.user32.AllowSetForegroundWindow(ASFW_ANY)
        for hwnd in (target_hwnd, occ_hwnd):
            tid = int(wh.user32.GetWindowThreadProcessId(wh.wintypes.HWND(hwnd), None))
            if wh.user32.AttachThreadInput(current_thread, tid, True):
                attached.append(tid)

        curve = []
        all_trials = []
        for dwell in DWELLS:
            bucket = []
            for _ in range(TRIALS):
                wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)
                bare_foreground(target_hwnd)
                time.sleep(0.08)

                def disturb():
                    bare_foreground(occ_hwnd)
                    if dwell > 0:
                        time.sleep(dwell)
                    bare_foreground(target_hwnd)
                    time.sleep(0.05)

                run = guard.wrap_with_events(disturb)
                poll_hit = any(fg == occ_hwnd for _, fg in run.foreground_events)
                hook_hit = any(fg == occ_hwnd for _, fg in run.hook_foreground_events)
                combined = sorted(run.foreground_events + run.hook_foreground_events)
                occ_ts = next((ts for ts, fg in combined if fg == occ_hwnd), None)
                tgt_ts = next(
                    (ts for ts, fg in combined if fg == target_hwnd and occ_ts is not None and ts > occ_ts),
                    None,
                )
                actual = round((tgt_ts - occ_ts) * 1000, 1) if occ_ts is not None and tgt_ts is not None else None
                hook_occ_ts = next((ts for ts, fg in run.hook_foreground_events if fg == occ_hwnd), None)
                hook_tgt_ts = next(
                    (ts for ts, fg in run.hook_foreground_events if fg == target_hwnd and hook_occ_ts is not None and ts > hook_occ_ts),
                    None,
                )
                hook_dwell = round((hook_tgt_ts - hook_occ_ts) * 1000, 1) if hook_occ_ts is not None and hook_tgt_ts is not None else None
                record = {
                    "requested_dwell_ms": dwell * 1000,
                    "actual_dwell_ms": actual,
                    "hook_dwell_ms": hook_dwell,
                    "poll_detected": poll_hit,
                    "hook_detected": hook_hit,
                    "detected": poll_hit or hook_hit,
                    "external_input_during_window": run.external_input_during_window,
                    "event_hook_active": run.event_hook_active,
                    "target_restored": run.after.foreground_hwnd == target_hwnd,
                    "poll_events": [fg for _, fg in run.foreground_events],
                    "hook_events": [fg for _, fg in run.hook_foreground_events],
                }
                bucket.append(record)
                all_trials.append(record)
            curve.append(
                {
                    "requested_dwell_ms": dwell * 1000,
                    "trials": len(bucket),
                    "poll_detected": sum(1 for r in bucket if r["poll_detected"]),
                    "hook_detected": sum(1 for r in bucket if r["hook_detected"]),
                    "any_detected": sum(1 for r in bucket if r["detected"]),
                    "actual_dwell_ms": [r["actual_dwell_ms"] for r in bucket],
                    "hook_dwell_ms": [r["hook_dwell_ms"] for r in bucket],
                    "external_input_true": sum(1 for r in bucket if r["external_input_during_window"]),
                }
            )
            print(
                f"dwell={dwell*1000:5.1f}ms poll={curve[-1]['poll_detected']}/{TRIALS} "
                f"hook={curve[-1]['hook_detected']}/{TRIALS} actual={curve[-1]['actual_dwell_ms']}"
            )

        clean = [r for r in all_trials if not r["external_input_during_window"]]
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "target_hwnd": target_hwnd,
            "occluder_hwnd": occ_hwnd,
            "injection": "bare SetForegroundWindow, thread input attached once, AllowSetForegroundWindow(ASFW_ANY)",
            "dwell_curve": curve,
            "trials": all_trials,
            "clean_trials": len(clean),
            "contaminated_trials": len(all_trials) - len(clean),
            "min_actual_dwell_ms": min((r["actual_dwell_ms"] for r in clean if r["actual_dwell_ms"] is not None), default=None),
            "min_hook_dwell_ms": min((r["hook_dwell_ms"] for r in clean if r["hook_dwell_ms"] is not None), default=None),
        }
        (out_dir / "dwell_limit.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'dwell_limit.json'}")
        print(f"min_actual_dwell_ms={result['min_actual_dwell_ms']} min_hook_dwell_ms={result['min_hook_dwell_ms']} clean={result['clean_trials']}/{len(all_trials)}")
        return 0
    finally:
        for tid in attached:
            wh.user32.AttachThreadInput(current_thread, tid, False)
        target_proc.terminate()
        occ_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
"""FocusGuard reliability over a larger sample (controlled target only).

Phase 1 E2 reported false positives on just 3 negatives and detection on 3
positives. This probe widens the sample: 30 idle negatives (false-positive rate)
and 15 injected foreground switches at ~100 ms dwell (detection rate), all against
the controlled native target window. No Trae/WeChat interaction, no messages.
Writes var/experiments/<run_id>/focusguard_reliability.json.
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

NEGATIVES = 30
POSITIVES = 15
DWELL = 0.1


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    target_proc = rx.start_app(x=220, y=180, auto_close=180)
    occ_proc = rx.start_app(occluder=True, x=760, y=180, w=300, h=200, auto_close=180)
    try:
        target = ux.find_window(rx.TARGET_TITLE, rx.TARGET_CLASS, timeout=8)
        occ = ux.find_window(rx.OCCLUDER_TITLE, rx.OCCLUDER_CLASS, timeout=8)
        if target is None or occ is None:
            print("ABORT: target/occluder not found")
            return 2
        target_hwnd = int(target.NativeWindowHandle)
        occ_hwnd = int(occ.NativeWindowHandle)
        guard = Win32FocusGuard(target_hwnd)
        wh.ensure_foreground(target_hwnd)
        time.sleep(0.5)

        negatives = []
        for i in range(NEGATIVES):
            wh.wait_for_quiescence(min_idle_ms=400, timeout=3.0)
            run = guard.wrap_with_events(lambda: time.sleep(0.2))
            negatives.append(
                {
                    "trial": i,
                    "unexpected": run.unexpected_focus_switch,
                    "external_input": run.external_input_during_window,
                    "poll_events": [fg for _, fg in run.foreground_events],
                    "hook_events": [fg for _, fg in run.hook_foreground_events],
                }
            )
        neg_clean = [n for n in negatives if not n["external_input"]]
        neg_fp = sum(1 for n in neg_clean if n["unexpected"])

        positives = []
        for i in range(POSITIVES):
            wh.wait_for_quiescence(min_idle_ms=400, timeout=3.0)
            wh.ensure_foreground(target_hwnd)
            time.sleep(0.08)

            def disturb():
                wh.quick_foreground(occ_hwnd)
                time.sleep(DWELL)
                wh.quick_foreground(target_hwnd)
                time.sleep(0.05)

            run = guard.wrap_with_events(disturb)
            poll_hit = any(fg == occ_hwnd for _, fg in run.foreground_events)
            hook_hit = any(fg == occ_hwnd for _, fg in run.hook_foreground_events)
            positives.append(
                {
                    "trial": i,
                    "poll_detected": poll_hit,
                    "hook_detected": hook_hit,
                    "detected": poll_hit or hook_hit,
                    "external_input": run.external_input_during_window,
                    "target_restored": run.after.foreground_hwnd == target_hwnd,
                }
            )
        pos_clean = [p for p in positives if not p["external_input"]]
        pos_detected = sum(1 for p in pos_clean if p["detected"])
        pos_poll = sum(1 for p in pos_clean if p["poll_detected"])
        pos_hook = sum(1 for p in pos_clean if p["hook_detected"])

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
            "negatives": negatives,
            "positives": positives,
            "negative_total": len(negatives),
            "negative_clean": len(neg_clean),
            "negative_false_positives": neg_fp,
            "false_positive_rate": (neg_fp / len(neg_clean)) if neg_clean else None,
            "positive_total": len(positives),
            "positive_clean": len(pos_clean),
            "positive_detected": pos_detected,
            "positive_poll_detected": pos_poll,
            "positive_hook_detected": pos_hook,
            "detection_rate": (pos_detected / len(pos_clean)) if pos_clean else None,
            "requested_dwell_ms": DWELL * 1000,
        }
        (out_dir / "focusguard_reliability.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'focusguard_reliability.json'}")
        print(
            f"negatives clean={len(neg_clean)}/{len(negatives)} FP={neg_fp} rate={result['false_positive_rate']}; "
            f"positives clean={len(pos_clean)}/{len(positives)} detected={pos_detected} "
            f"poll={pos_poll} hook={pos_hook} rate={result['detection_rate']}"
        )
        return 0
    finally:
        target_proc.terminate()
        occ_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
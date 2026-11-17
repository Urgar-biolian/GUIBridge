"""Ground the OCR locate-only channel's focus-interference risk in real data.

Principle 3 treats OCR/vision as locate-only (never background input); principle 4
requires every channel to declare a MEASURED risk, not an assumed one. The OCR
channel (packages/perception/ocr.py) captures a window region passively with mss
and runs RapidOCR on the image, yielding GUIElements with actions=[] — but its
NONE interference risk had not been FocusGuard-measured. This probe measures it
on the controlled self-drawn target (GDI-painted text, NO UIA content semantics —
the exact case where OCR is the locate fallback, contrast run 20261117T102927Z).

STRICTLY READ-ONLY: passive screen capture + offline OCR inference only. No
clicks, no input injection, no messages, no mode switch. The capture region is
the controlled target window only; the PNG and JSON land in gitignored
var/experiments/<run_id>/ and are not committed. Located text is the target's own
demo labels (not user data). Writes ocr_locate_focus.json.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import uia_exec as ux  # noqa: E402
import run_experiments as rx  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from packages.perception.ocr import (  # noqa: E402
    OcrUnavailable,
    OCRChannel,
    elements_from_ocr,
    grab_window_png,
)

SELFDRAWN_TITLE = "GUIBridge SelfDrawn Target"
SELFDRAWN_CLASS = "GUIBridgeSelfDrawnWindow"
TRIALS = 3


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("selfdrawn_app.py")),
         "--x", "220", "--y", "180", "--auto-close-seconds", "120"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        sd = ux.find_window(SELFDRAWN_TITLE, SELFDRAWN_CLASS, timeout=8)
        if sd is None:
            print("ABORT: self-drawn target window not found")
            return 2
        hwnd = int(sd.NativeWindowHandle)
        window_id = format(hwnd, "x")
        guard = Win32FocusGuard(hwnd)
        ocr = OCRChannel()
        print(f"selfdrawn hwnd={hwnd} title={wh.window_title(hwnd)!r}")

        trials = []
        for i in range(TRIALS):
            wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)

            def locate():
                png = grab_window_png(window_id, out_dir=str(out_dir))
                boxes = ocr.read_text_boxes(png)
                elements = elements_from_ocr(boxes, window_id)
                return {"png": png, "boxes": boxes, "elements": elements}

            try:
                run = guard.wrap_with_events(locate)
            except OcrUnavailable as exc:
                print(f"ABORT: OCR/capture dependency unavailable: {exc}")
                return 2
            res = run.result
            elements = res["elements"]
            locate_only = all(e.actions == [] and e.role == "text" for e in elements)
            record = {
                "trial": i,
                "text_box_count": len(res["boxes"]),
                "element_count": len(elements),
                "locate_only_no_actions": locate_only,
                "located_texts": [b["text"] for b in res["boxes"]],
                "target_active_at_start": run.before.target_active,
                "cursor_displacement": run.cursor_displacement,
                "unexpected_focus_switch": run.unexpected_focus_switch,
                "external_input_during_window": run.external_input_during_window,
                "event_hook_active": run.event_hook_active,
                "poll_events": [fg for _, fg in run.foreground_events],
                "hook_events": [fg for _, fg in run.hook_foreground_events],
            }
            trials.append(record)
            print(
                f"trial {i}: boxes={record['text_box_count']} locate_only={locate_only} "
                f"cursor={record['cursor_displacement']} focus_switch={record['unexpected_focus_switch']} "
                f"ext={record['external_input_during_window']}"
            )
            time.sleep(0.3)

        clean = [t for t in trials if t["text_box_count"] > 0 and not t["external_input_during_window"]]
        no_interference = [
            t for t in clean if not t["unexpected_focus_switch"] and t["cursor_displacement"] == 0
        ]
        measured = "none" if clean and len(no_interference) == len(clean) else "unknown"
        locate_only_all = all(t["locate_only_no_actions"] for t in trials)
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "selfdrawn_hwnd": hwnd,
            "channel": "OCR_VISION (packages/perception/ocr.py: mss capture + RapidOCR)",
            "action": "read-only passive window capture + offline OCR; no clicks/input/messages",
            "purpose": "measure OCR locate-only focus risk (principle 4) on the UIA-negative self-drawn target",
            "uia_contrast_run": "20261117T102927Z (self-drawn content exposes no UIA semantics)",
            "trials": trials,
            "clean_trials": len(clean),
            "no_interference_trials": len(no_interference),
            "locate_only_all_trials": locate_only_all,
            "measured_locate_risk": measured,
            "note": (
                "OCR yields locate-only GUIElements (role=text, actions=[]); it locates painted "
                "text but injects no input. Passive capture + offline inference observed "
                "interference-free -> NONE risk for the locate/read use, never an execution channel."
            ),
        }
        (out_dir / "ocr_locate_focus.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'ocr_locate_focus.json'}")
        print(
            f"clean={len(clean)}/{TRIALS} no_interference={len(no_interference)} "
            f"locate_only_all={locate_only_all} measured_locate_risk={measured}"
        )
        return 0 if (measured == "none" and locate_only_all) else 1
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
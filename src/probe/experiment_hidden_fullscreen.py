"""E14: hidden-desktop FULL-SCREEN capture, measured on benign targets (NO WeChat login).

Question: can we screenshot the WHOLE hidden (virtual) desktop, not just one window, so an
agent can later look at the entire scene and self-correct? Two worker-side methods are
compared (see hidden_capture.py): BitBlt of the virtual screen vs PrintWindow-stitch of all
visible windows. Targets are native_test_app standard-control windows launched on the hidden
desktop — no real app, no phone login, no private content, so PNGs are kept for inspection.

Capture is read-only; host foreground/cursor must stay untouched. Raw JSON + PNGs ->
var/experiments/<run_id>/ (gitignored). The frozen Channel enum is NOT modified.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE_DIR = Path(__file__).parent
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import experiment_hidden_desktop as e8  # noqa: E402
import hidden_capture as hc  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = e8.user32
GENERIC_ALL = e8.GENERIC_ALL


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBFull_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results: dict = {"run_id": run_id, "desktop": desktop, "createdesktop_ok": bool(hdesk)}
    procs = []
    worker = None
    try:
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())  # noqa: F821
        worker = e8.DesktopWorker(int(hdesk))
        results["worker_desktop_ok"] = worker.desktop_ok
        if worker.start_error:
            raise RuntimeError(worker.start_error)

        # Two benign windows at different positions on the hidden desktop.
        targets = []
        for (x, y) in ((660, 260), (1120, 320)):
            proc, hwnd, desktop_ok = e8._launch_on_desktop(desktop, x, y)
            procs.append(proc)
            targets.append({"hwnd": hwnd, "thread_desktop_confirmed": desktop_ok,
                            "rect": list(wh.window_rect(hwnd))})
        results["targets"] = targets
        time.sleep(1.5)  # let windows paint

        results["host_fg_before"] = int(user32.GetForegroundWindow() or 0)
        results["host_cursor_before"] = list(wh.cursor_pos())

        results["full_capture"] = hc.capture_full(worker, str(run_dir))

        # Per-window reference (the already-proven single-window path) for comparison.
        results["per_window"] = [
            {"hwnd": t["hwnd"], **worker.run(lambda h=t["hwnd"]: e8._capture_feasibility(h))}
            for t in targets]

        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_cursor_after"] = list(wh.cursor_pos())
        results["host_foreground_changed"] = results["host_fg_after"] != results["host_fg_before"]
        results["host_cursor_displacement"] = (
            abs(results["host_cursor_after"][0] - results["host_cursor_before"][0])
            + abs(results["host_cursor_after"][1] - results["host_cursor_before"][1]))
        results["verdict"] = "captured"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
        results["verdict"] = "error"
    finally:
        if worker is not None:
            worker.close()
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))

    output = run_dir / "hidden_fullscreen.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    fc = results.get("full_capture", {})
    bb = fc.get("bitblt", {})
    st = fc.get("stitch", {})
    summary = {
        "run_id": run_id,
        "output": str(output),
        "verdict": results.get("verdict"),
        "bitblt": {k: bb.get(k) for k in ("ok", "nonblack_ratio", "distinct_colors_sampled", "bitblt_return", "path")},
        "stitch": {k: st.get(k) for k in ("ok", "nonblack_ratio", "distinct_colors_sampled", "window_count", "path")},
        "host_foreground_changed": results.get("host_foreground_changed"),
        "host_cursor_displacement": results.get("host_cursor_displacement"),
        "closedesktop_ok": results.get("closedesktop_ok"),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
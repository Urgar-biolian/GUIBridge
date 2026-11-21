"""Long-duration / high-volume PostMessage click stress test on a hidden self-drawn target.

Benign local target (selfdrawn_app, no login, no real app): paints its own button and puts
clicked=N in the window title (--title-status). We PostMessage WM_LBUTTONDOWN/UP at the
painted button in batches on the hidden desktop, read the title counter after each batch to
measure CLICK LOSS, and sample the HOST foreground + cursor every batch to prove zero
interference over time. Fail-stop on host foreground change or unreadable title (principle 6).

Metrics: posted vs registered clicks (loss), clicks/sec, elapsed, host fg/cursor stability,
per-batch timeline. Raw JSON -> var/experiments/<run_id>/ (gitignored). No SendInput, no
SwitchDesktop; the hidden target is terminated and the desktop closed at the end.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE_DIR = Path(__file__).parent
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import experiment_hidden_desktop as e8  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = e8.user32
GENERIC_ALL = e8.GENERIC_ALL
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
BUTTON_LP = (68 << 16) | (95 & 0xFFFF)  # painted button client center (95,68)


def _count(title: str):
    if "clicked=" in title:
        try:
            return int(title.rsplit("clicked=", 1)[1])
        except ValueError:
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clicks", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--delay", type=float, default=0.001, help="per-click delay seconds")
    ap.add_argument("--max-seconds", type=float, default=120.0)
    args = ap.parse_args()

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBStress_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results: dict = {"run_id": run_id, "clicks_target": args.clicks, "batch": args.batch,
                     "createdesktop_ok": bool(hdesk)}
    proc = None
    worker = None
    try:
        si = subprocess.STARTUPINFO()
        si.lpDesktop = desktop
        proc = subprocess.Popen(
            [sys.executable, str(PROBE_DIR / "selfdrawn_app.py"), "--x", "660", "--y", "260",
             "--w", "420", "--h", "240", "--title-status", "--show-no-activate",
             "--auto-close-seconds", str(int(args.max_seconds) + 120)],
            startupinfo=si, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        line = proc.stdout.readline()
        hwnd = int(line.split("=", 1)[1]) if "WINDOW_HANDLE=" in line else 0
        results["hwnd"] = hwnd
        worker = e8.DesktopWorker(int(hdesk))
        time.sleep(1.0)
        fg0 = int(user32.GetForegroundWindow() or 0)
        cur0 = wh.cursor_pos()
        results["host_fg_before"] = fg0
        t0 = worker.run(lambda: wh.window_title(hwnd))
        base = _count(t0) or 0

        def title():
            return wh.window_title(hwnd)

        posted, registered = 0, base
        timeline, anomalies = [], []
        max_cursor = 0
        start = time.time()
        prev = base
        stalls = 0
        while posted < args.clicks and time.time() - start < args.max_seconds:
            n = min(args.batch, args.clicks - posted)

            def batch(n=n):
                for _ in range(n):
                    user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONDOWN, 1, BUTTON_LP)
                    user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONUP, 0, BUTTON_LP)
                    time.sleep(args.delay)
            worker.run(batch)
            posted += n
            time.sleep(0.15)  # let the hidden message queue drain
            c = worker.run(title)
            fg = int(user32.GetForegroundWindow() or 0)
            cx, cy = wh.cursor_pos()
            max_cursor = max(max_cursor, abs(cx - cur0[0]) + abs(cy - cur0[1]))
            reg = _count(c)
            timeline.append({"posted": posted, "registered": reg,
                             "elapsed": round(time.time() - start, 2)})
            if fg != fg0:
                anomalies.append("host_foreground_changed")
                break
            if reg is None:
                anomalies.append("title_unreadable")
                break
            if reg == prev:
                stalls += 1
                if stalls >= 2:
                    anomalies.append("click_counter_stalled")
                    break
            else:
                stalls = 0
            prev = reg
            registered = reg
        elapsed = time.time() - start
        results["posted"] = posted
        results["registered"] = registered
        results["click_loss"] = posted - (registered - base)
        results["clicks_per_sec"] = round(posted / max(elapsed, 0.001), 1)
        results["elapsed_sec"] = round(elapsed, 2)
        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results["host_fg_after"] != fg0
        results["host_cursor_max_displacement"] = max_cursor
        results["anomalies"] = anomalies
        results["timeline_tail"] = timeline[-5:]
        results["batches"] = len(timeline)
        ok = not anomalies and results["click_loss"] == 0 and not results["host_foreground_changed"]
        results["verdict"] = "stress_ok" if ok else "stress_loss_or_anomaly"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["verdict"] = "error"
    finally:
        if worker is not None:
            worker.close()
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.kill()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(wintypes.HANDLE(int(hdesk))))
    out = run_dir / "stress_click.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in
                      ("run_id", "verdict", "posted", "registered", "click_loss", "clicks_per_sec",
                       "elapsed_sec", "batches", "host_foreground_changed",
                       "host_cursor_max_displacement", "anomalies", "closedesktop_ok", "error")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
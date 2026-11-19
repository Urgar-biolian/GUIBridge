"""E15a: does PostMessage mouse drive a SELF-DRAWN surface on the hidden desktop?

Answers the mechanism question WITHOUT any WeChat login: selfdrawn_app paints its own
button/edit (no child HWNDs, no UIA semantics), same shape as WeChat's chat render surface.
PostMessage WM_LBUTTONDOWN at the painted button must increment its clicked counter
(read via --title-status window title). Also probe WM_CHAR / WM_PASTE (the app has no edit
handler, so these are expected no-ops here — isolating mouse-click from text-injection).
Host foreground/cursor measured. Benign local target; JSON -> var/experiments (gitignored).
"""

from __future__ import annotations

import ctypes
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
WM_CHAR, WM_PASTE = 0x0102, 0x0302
CLASS = "GUIBridgeSelfDrawnWindow"


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBSelf_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results: dict = {"run_id": run_id, "createdesktop_ok": bool(hdesk)}
    proc = None
    worker = None
    try:
        si = subprocess.STARTUPINFO()
        si.lpDesktop = desktop
        proc = subprocess.Popen(
            [sys.executable, str(PROBE_DIR / "selfdrawn_app.py"), "--x", "660", "--y", "260",
             "--w", "420", "--h", "240", "--title-status", "--show-no-activate",
             "--auto-close-seconds", "120"],
            startupinfo=si, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        line = proc.stdout.readline()
        hwnd = int(line.split("=", 1)[1]) if "WINDOW_HANDLE=" in line else 0
        results["hwnd"] = hwnd
        worker = e8.DesktopWorker(int(hdesk))
        time.sleep(1.0)
        results["host_fg_before"] = int(user32.GetForegroundWindow() or 0)

        def title():
            return wh.window_title(hwnd)
        results["title_before"] = worker.run(title)

        # PostMessage mouse at the painted button (client 20..170 x 50..86 -> center 95,68).
        def click():
            wx, wy, _, _ = wh.window_rect(hwnd)
            lp = (68 << 16) | (95 & 0xFFFF)
            user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONDOWN, 1, lp)
            user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONUP, 0, lp)
        worker.run(click)
        time.sleep(0.8)
        results["title_after_mouse"] = worker.run(title)
        results["mouse_click_registered"] = results["title_after_mouse"] != results["title_before"]

        # Text-injection messages: app has no edit handler -> expect no title change.
        def paste():
            user32.PostMessageW(wintypes.HWND(hwnd), WM_PASTE, 0, 0)
        def chars():
            for c in "abc":
                user32.PostMessageW(wintypes.HWND(hwnd), WM_CHAR, ord(c), 0)
        worker.run(paste)
        worker.run(chars)
        time.sleep(0.8)
        results["title_after_text"] = worker.run(title)
        results["text_messages_effect"] = results["title_after_text"] != results["title_after_mouse"]

        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results["host_fg_after"] != results["host_fg_before"]
        results["verdict"] = "measured"
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
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))
    out = run_dir / "selfdrawn_hidden_click.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in
                      ("run_id", "verdict", "mouse_click_registered", "text_messages_effect",
                       "title_before", "title_after_mouse", "host_foreground_changed",
                       "closedesktop_ok", "error")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
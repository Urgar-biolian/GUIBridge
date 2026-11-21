"""Live mirror of the hidden desktop on a MAIN-desktop window (recording / demo impact).

Attaches to the keep-alive hidden WeChat session, periodically PrintWindow-stitches the
hidden desktop (E14 hidden_capture.capture_stitch), crops to the content bounding box,
scales it, and displays it in a tkinter window on the user's VISIBLE desktop. Capture runs
on the hidden-desktop worker (read-only; host foreground/cursor untouched by the capture).
Only the mirror window itself is visible on the host.

Privacy: this DOES show real chat content on screen. For public recording use a benign
target (e.g. the self-drawn stress app) or accept that private chats are visible. Temp PNGs
live outside the repo and are deleted on exit. The keep-alive stub is NOT killed on exit.

Run: python src/probe/hidden_mirror.py [--width 1000] [--interval 0.6] [--full]
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = Path(__file__).parent
for _p in (str(ROOT), str(PROBE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experiment_hidden_desktop as e8  # noqa: E402
import hidden_capture  # noqa: E402
import hidden_session  # noqa: E402

user32 = e8.user32


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1000, help="display width in px")
    ap.add_argument("--interval", type=float, default=0.6, help="seconds between captures")
    ap.add_argument("--full", action="store_true", help="show full virtual screen (no content crop)")
    args = ap.parse_args()

    hdesk, worker, ch, state = hidden_session.ensure_session()
    tmp = tempfile.mkdtemp(prefix="gb_mirror_")
    bufs = [os.path.join(tmp, "m0.png"), os.path.join(tmp, "m1.png")]
    raw = os.path.join(tmp, "raw.png")
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def capture_loop():
        i = 0
        while not stop.is_set():
            try:
                st = worker.run(lambda: hidden_capture.capture_stitch(raw))
                im = Image.open(raw)
                if not args.full:
                    wins = st.get("windows", [])
                    vx, vy, vw, vh = st["virtual_screen"]
                    if wins:
                        xs = [w["rect"][0] - vx for w in wins]
                        ys = [w["rect"][1] - vy for w in wins]
                        xe = [w["rect"][0] - vx + w["rect"][2] for w in wins]
                        ye = [w["rect"][1] - vy + w["rect"][3] for w in wins]
                        box = (max(min(xs), 0), max(min(ys), 0), min(max(xe), vw), min(max(ye), vh))
                        if box[2] > box[0] and box[3] > box[1]:
                            im = im.crop(box)
                w0, h0 = im.size
                nh = max(1, int(h0 * args.width / max(w0, 1)))
                im = im.resize((args.width, nh))
                out = bufs[i % 2]
                im.save(out)
                i += 1
                q.put((out, st.get("window_count", 0)))
            except Exception as exc:  # noqa: BLE001
                q.put((None, repr(exc)))
            stop.wait(args.interval)

    th = threading.Thread(target=capture_loop, daemon=True)
    th.start()

    root = tk.Tk()
    root.title("GUIBridge 隐藏桌面镜像 — host zero-interference")
    label = tk.Label(root)
    label.pack()
    status = tk.Label(root, text="connecting...", anchor="w")
    status.pack(fill="x")
    photo = [None]

    def poll():
        try:
            while True:
                out, info = q.get_nowait()
                if out:
                    photo[0] = ImageTk.PhotoImage(Image.open(out))
                    label.config(image=photo[0])
                    fg = int(user32.GetForegroundWindow() or 0)
                    status.config(text=f"hidden_windows={info}  host_fg={fg}  stub={state['stub_pid']}  width={args.width}")
                else:
                    status.config(text=f"capture error: {info}")
        except queue.Empty:
            pass
        if not stop.is_set():
            root.after(120, poll)

    def on_close():
        stop.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(120, poll)
    try:
        root.mainloop()
    finally:
        stop.set()
        th.join(timeout=3)
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
        for f in Path(tmp).glob("*.png"):
            f.unlink(missing_ok=True)
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
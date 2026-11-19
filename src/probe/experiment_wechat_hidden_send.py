"""E15: hidden-desktop OCR-locate + PostMessage SEND test (answers "why not just test it?").

Prior "zero-interference send impossible" rested on an UNMEASURED inference that PostMessage
is unreliable on the self-drawn chat render surface. This probe MEASURES it instead of assuming:
single keep-alive login of the saved second account -> worker PrintWindow screenshot -> OCR
locate (send button / 文件传输助手 row) -> PostMessage click the row (OCR title gate) -> click
composer + inject text via WM_PASTE / WM_CHAR (OCR verify staged) -> PostMessage click send at
OCR coords (OCR verify bubble). Every step gated; failure stops, no blind retry (principle 6).

Target is ONLY 文件传输助手 (benign self-transfer). Privacy: OCR boxes are read in-memory and
only benign labels/rects/booleans are persisted; private chat/contact text is NEVER stored;
each screenshot PNG is deleted right after OCR. Host foreground/cursor measured (must stay put).
Raw JSON -> var/experiments/<run_id>/ (gitignored). Frozen Channel enum NOT modified.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import sys
import tempfile
import time
import traceback
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE_DIR = Path(__file__).parent
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_real_app_hidden as e9  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402
import experiment_wechat_send as e11  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.perception.ocr import OCRChannel  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = e8.user32
GENERIC_ALL = e8.GENERIC_ALL
WM_CHAR, WM_PASTE = 0x0102, 0x0302
SEND, TARGET = "发送", "文件传输助手"


def _ocr_boxes(worker, ch: int, tmp_dir: str, ocr: OCRChannel) -> list[dict]:
    """Worker PrintWindow -> PNG -> OCR -> delete PNG. Boxes stay in memory only."""
    png = os.path.join(tmp_dir, "chat_ocr.png")
    worker.run(lambda: e13._capture_png(ch, png))
    if not os.path.exists(png):
        return []
    try:
        return ocr.read_text_boxes(png)
    finally:
        os.remove(png)


def _screen_rect(ch: int, bounds) -> list:
    ox, oy, _, _ = wh.window_rect(ch)
    x1, y1, x2, y2 = bounds
    return [x1 + ox, y1 + oy, x2 + ox, y2 + oy]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", choices=["login", "locate", "stage", "send"], default="send")
    ap.add_argument("--text", default="GB hidden send test")
    args = ap.parse_args()

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="gb_wxsend_")
    desktop = f"GBSend_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results: dict = {"run_id": run_id, "desktop": desktop, "upto": args.upto,
                     "createdesktop_ok": bool(hdesk)}
    ocr = OCRChannel()
    worker = None
    launch = {}
    try:
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())
        worker = e8.DesktopWorker(int(hdesk))
        results["worker_desktop_ok"] = worker.desktop_ok
        launch = e9._launch_real(e13.WECHAT_EXE, desktop)
        results["launch"] = launch
        if not launch.get("ok"):
            raise RuntimeError(f"launch failed: {launch}")
        results["host_fg_before"] = int(user32.GetForegroundWindow() or 0)

        # --- login (keep-alive within this run): auto-enter saved second account ---
        logged_in, ch, auto = False, None, False
        deadline = time.time() + 180
        while time.time() < deadline and not logged_in:
            mains = e13._qt_mains(worker)
            if mains:
                biggest = max(mains, key=lambda m: m["area"])
                if biggest["rect"][2] < 600:
                    lh = biggest["hwnd"]
                    texts = worker.run(lambda h=lh: e13._login_texts(h))
                    nick = next((t for t in texts if t not in e13.LOGIN_KNOWN_LABELS), None)
                    if nick and nick != e13.HOST_NICK and not auto:
                        btn = worker.run(lambda h=lh: e13._find_switch_control(h, "进入微信"))
                        if not btn.get("found"):
                            btn = worker.run(lambda h=lh: e13._find_switch_control(h, "登录"))
                        if btn.get("found"):
                            worker.run(lambda h=lh, r=btn["rect"]: e13._click_switch(h, r))
                            auto = True
                            results["auto_enter_nick"] = nick
                else:
                    logged_in, ch = True, biggest["hwnd"]
            time.sleep(0.5)
        results["logged_in"] = logged_in
        if not logged_in or args.upto == "login":
            results["verdict"] = "logged_in" if logged_in else "login_timeout"
            raise _Stop()
        time.sleep(3.0)

        # --- locate ---
        boxes = _ocr_boxes(worker, ch, tmp_dir, ocr)
        send = [b for b in boxes if SEND in b["text"]]
        row = [b for b in boxes if b["text"].strip() == TARGET]
        results["locate"] = {
            "box_count": len(boxes),
            "send_found": bool(send),
            "send_rect_screen": _screen_rect(ch, send[0]["bounds"]) if send else None,
            "target_row_found": bool(row),
            "target_row_rect_screen": _screen_rect(ch, row[0]["bounds"]) if row else None,
        }
        if args.upto == "locate":
            results["verdict"] = "located"
            raise _Stop()

        # --- open target chat (PostMessage click row) + OCR title gate ---
        opened = {"clicked": False, "title_verified": False}
        if row:
            worker.run(lambda r=_screen_rect(ch, row[0]["bounds"]): e13._click_switch(ch, r))
            time.sleep(1.5)
            b2 = _ocr_boxes(worker, ch, tmp_dir, ocr)
            _, _, w, h = wh.window_rect(ch)
            title = [b for b in b2 if b["text"].strip() == TARGET
                     and b["bounds"][0] > 0.3 * w and b["bounds"][1] < 0.2 * h]
            opened = {"clicked": True, "title_verified": bool(title)}
        else:
            opened["reason"] = "target_not_in_recent_list"
        results["open_target"] = opened
        if not opened["title_verified"] or args.upto == "locate":
            results["verdict"] = "target_not_opened"
            raise _Stop()

        # --- stage: click composer region, inject via WM_PASTE then WM_CHAR, OCR verify ---
        _, _, w, h = wh.window_rect(ch)
        composer = [int(0.4 * w), int(0.8 * h), int(0.9 * w), int(0.95 * h)]
        worker.run(lambda r=_screen_rect(ch, composer): e13._click_switch(ch, r))
        time.sleep(0.8)
        kids = worker.run(lambda: e13._child_hwnds(ch))
        render = next((k["hwnd"] for k in kids if "mmuirender" in k["class"].lower()), ch)
        e11.clipboard_write(args.text)  # clipboard is global; set from host thread
        staged, methods = False, []
        _, _, w, h = wh.window_rect(ch)
        composer_y = 0.7 * h  # composer occupies the bottom band; message list above it

        def staged_now():
            bs = _ocr_boxes(worker, ch, tmp_dir, ocr)
            return any(args.text in b["text"] and b["bounds"][1] > composer_y for b in bs)
        for label, fn in (
            ("WM_PASTE", lambda h: user32.PostMessageW(wintypes.HWND(int(h)), WM_PASTE, 0, 0)),
            ("WM_CHAR", lambda h: [user32.PostMessageW(wintypes.HWND(int(h)), WM_CHAR, ord(c), 0)
                                   for c in args.text]),
        ):
            for h in (render, ch):
                worker.run(lambda hh=h, f=fn: f(hh))
                time.sleep(1.0)
                staged = staged_now()
                methods.append({"method": label, "hwnd": int(h), "staged": staged})
                if staged:
                    break
            if staged:
                break
        results["stage"] = {"staged": staged, "methods": methods}
        if not staged or args.upto == "stage":
            results["verdict"] = "staged" if staged else "stage_failed"
            raise _Stop()

        # --- send: click OCR-located 发送 on the hwnd that owns it (render child first,
        # then main), verify airtight: text appears in MESSAGE area AND composer is empty.
        def send_state():
            bs = _ocr_boxes(worker, ch, tmp_dir, ocr)
            in_msg = any(args.text in b["text"] and b["bounds"][3] < composer_y for b in bs)
            in_composer = any(args.text in b["text"] and b["bounds"][1] > composer_y for b in bs)
            return in_msg, in_composer
        sent = False
        attempts = []
        for h in (render, ch):
            b3 = _ocr_boxes(worker, ch, tmp_dir, ocr)
            send3 = [b for b in b3 if SEND in b["text"]]
            if not send3:
                attempts.append({"hwnd": int(h), "send_found": False})
                continue
            worker.run(lambda hh=h, r=_screen_rect(ch, send3[0]["bounds"]): e13._click_switch(hh, r))
            time.sleep(1.5)
            in_msg, in_composer = send_state()
            sent = in_msg and not in_composer
            attempts.append({"hwnd": int(h), "send_found": True,
                             "bubble_in_message_area": in_msg, "composer_empty": not in_composer,
                             "sent": sent})
            if sent:
                break
        results["send"] = {"attempts": attempts, "sent_verified": sent}
        results["verdict"] = "hidden_send_verified" if sent else "send_not_verified"
    except _Stop:
        pass
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
        results["verdict"] = "error"
    finally:
        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results.get("host_fg_after") != results.get("host_fg_before")
        if launch.get("ok"):
            results["cleanup_stub"] = e13._cleanup_stub(launch["pid"])
        if worker is not None:
            worker.close()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))
        for f in Path(tmp_dir).glob("*.png"):
            f.unlink(missing_ok=True)
        os.rmdir(tmp_dir) if not list(Path(tmp_dir).iterdir()) else None

    output = run_dir / "wechat_hidden_send.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: results.get(k) for k in
               ("run_id", "verdict", "logged_in", "locate", "open_target", "stage", "send",
                "host_foreground_changed", "closedesktop_ok", "error")}
    summary["output"] = str(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


class _Stop(Exception):
    pass


if __name__ == "__main__":
    sys.exit(main())
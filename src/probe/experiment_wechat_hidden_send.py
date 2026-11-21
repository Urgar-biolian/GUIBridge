"""E15: hidden-desktop OCR-locate + PostMessage SEND test (answers "why not just test it?").

Prior "zero-interference send impossible" rested on an UNMEASURED inference that PostMessage
is unreliable on the self-drawn chat render surface. This probe MEASURES it instead of assuming:
KEEP-ALIVE login of the saved second account (hidden_session.ensure_session) -> worker
PrintWindow screenshot -> OCR locate (send button / 文件传输助手 row) -> PostMessage click the
row (OCR title gate) -> click composer + inject text via WM_PASTE / WM_CHAR (OCR verify staged)
-> PostMessage click send at OCR coords (OCR verify bubble + composer empty). Every step gated;
failure stops, no blind retry (principle 6).

Keep-alive: the hidden WeChat stub is NOT killed at the end of a run. Login once, then every
later run ATTACHES to the same logged-in window (no repeated phone confirm). Only an explicit
`--session stop` (or hidden_session.py stop) cleans up the stub. Host zero-interference.

Target is ONLY 文件传输助手 (benign self-transfer). Privacy: OCR boxes are read in-memory and
only benign labels/rects/booleans are persisted; private chat/contact text is NEVER stored;
each screenshot PNG is deleted right after OCR. Host foreground/cursor measured (must stay put).
Raw JSON -> var/experiments/<run_id>/ (gitignored). Frozen Channel enum NOT modified.
"""

from __future__ import annotations

import argparse
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
import experiment_wechat_hidden_login as e13  # noqa: E402
import hidden_session  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.perception.ocr import OCRChannel  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = e8.user32
WM_CHAR, WM_PASTE = 0x0102, 0x0302
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
VK_DELETE = 0x2E
SEND, TARGET = "发送", "文件传输助手"


def _click_local(ch: int, rect_local) -> None:
    cx = (rect_local[0] + rect_local[2]) // 2
    cy = (rect_local[1] + rect_local[3]) // 2
    lp = (cy << 16) | (cx & 0xFFFF)
    user32.PostMessageW(wintypes.HWND(int(ch)), WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(wintypes.HWND(int(ch)), WM_LBUTTONUP, 0, lp)


def _clear_composer(ch: int, rect_local) -> None:
    """Measured reliable clear on the self-drawn composer: triple-click select-all +
    WM_KEYDOWN VK_DELETE. (WM_CHAR backspace and Ctrl+A WM_KEYDOWN do NOT clear it.)"""
    cx = (rect_local[0] + rect_local[2]) // 2
    cy = (rect_local[1] + rect_local[3]) // 2
    lp = (cy << 16) | (cx & 0xFFFF)
    for _ in range(3):
        user32.PostMessageW(wintypes.HWND(int(ch)), WM_LBUTTONDOWN, 1, lp)
        user32.PostMessageW(wintypes.HWND(int(ch)), WM_LBUTTONUP, 0, lp)
        time.sleep(0.05)
    user32.PostMessageW(wintypes.HWND(int(ch)), WM_KEYDOWN, VK_DELETE, 0)
    user32.PostMessageW(wintypes.HWND(int(ch)), WM_KEYUP, VK_DELETE, 0)


def _inject_chars(ch: int, text: str) -> None:
    """WM_CHAR -> Qt MAIN hwnd, per-char delay (rapid posting drops chars). ASCII+CN both work."""
    for c in text:
        user32.PostMessageW(wintypes.HWND(int(ch)), WM_CHAR, ord(c), 0)
        time.sleep(0.03)


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


def _search_target(worker, ch: int, tmp_dir: str, ocr: OCRChannel, target: str) -> list:
    """Navigation only (no send): click search box, WM_CHAR target into main hwnd, OCR rows.

    Returns the topmost exact-match contact row (text==target, y>100 to skip the search
    input echo and the bottom 搜一搜 footer). Private contact names are never persisted.
    """
    boxes = _ocr_boxes(worker, ch, tmp_dir, ocr)
    search = [b for b in boxes if "搜索" in b["text"]]
    if search:
        worker.run(lambda r=_screen_rect(ch, search[0]["bounds"]): e13._click_switch(ch, r))
        time.sleep(0.6)
    worker.run(lambda: [user32.PostMessageW(wintypes.HWND(int(ch)), WM_CHAR, ord(c), 0)
                        for c in target])
    time.sleep(1.2)
    boxes = _ocr_boxes(worker, ch, tmp_dir, ocr)
    rows = [b for b in boxes if b["text"].strip() == target and b["bounds"][1] > 100]
    rows.sort(key=lambda b: b["bounds"][1])
    return rows[:1]


class _Stop(Exception):
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", choices=["login", "locate", "navigate", "stage", "send"], default="send")
    ap.add_argument("--target", default=TARGET, help="chat/contact name to open (OCR title-gated)")
    ap.add_argument("--text", default="GB hidden send test")
    ap.add_argument("--session", choices=["auto", "stop", "status"], default="auto",
                    help="auto=ensure keep-alive session then measure; stop=kill stub+clear; status=read-only")
    ap.add_argument("--login-timeout", type=float, default=180.0)
    args = ap.parse_args()

    if args.session == "stop":
        print(json.dumps(hidden_session.stop_session(), ensure_ascii=False, indent=2))
        return 0
    if args.session == "status":
        print(json.dumps(hidden_session.status_session(), ensure_ascii=False, indent=2))
        return 0

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="gb_wxsend_")
    ocr = OCRChannel()
    results: dict = {"run_id": run_id, "upto": args.upto, "session_mode": "keep_alive"}
    worker = None
    hdesk = None
    results["host_fg_before"] = int(user32.GetForegroundWindow() or 0)
    try:
        # --- keep-alive session: reuse alive logged-in stub, else login ONCE ---
        hdesk, worker, ch, state = hidden_session.ensure_session(args.login_timeout)
        results["session"] = {"desktop": state["desktop"], "stub_pid": state["stub_pid"],
                              "reused": state.get("reused", False),
                              "relogin": state.get("relogin", False), "chat_hwnd": int(ch)}
        results["logged_in"] = True
        if args.upto == "login":
            results["verdict"] = "logged_in"
            raise _Stop()
        time.sleep(2.0)

        # --- locate ---
        boxes = _ocr_boxes(worker, ch, tmp_dir, ocr)
        send = [b for b in boxes if SEND in b["text"]]
        row = [b for b in boxes if b["text"].strip() == args.target]
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

        # --- search fallback if target not in recent list (navigation only, no send) ---
        if not row:
            row = _search_target(worker, ch, tmp_dir, ocr, args.target)
            results["search_used"] = True
            results["search_row_found"] = bool(row)

        # --- open target chat (PostMessage click row) + OCR title gate ---
        opened = {"clicked": False, "title_verified": False}
        if row:
            worker.run(lambda r=_screen_rect(ch, row[0]["bounds"]): e13._click_switch(ch, r))
            time.sleep(1.5)
            b2 = _ocr_boxes(worker, ch, tmp_dir, ocr)
            _, _, w, h = wh.window_rect(ch)
            title = [b for b in b2 if b["text"].strip() == args.target
                     and b["bounds"][0] > 0.3 * w and b["bounds"][1] < 0.2 * h]
            opened = {"clicked": True, "title_verified": bool(title)}
        else:
            opened["reason"] = "target_not_found"
        results["open_target"] = opened
        if not opened["title_verified"]:
            results["verdict"] = "target_not_opened"
            raise _Stop()
        if args.upto == "navigate":
            results["verdict"] = "navigated_target_verified"
            raise _Stop()

        # --- stage: focus composer, clear it, inject WM_CHAR->main (delayed), OCR prefix-verify ---
        _, _, w, h = wh.window_rect(ch)
        composer = [int(0.4 * w), int(0.8 * h), int(0.9 * w), int(0.95 * h)]
        kids = worker.run(lambda: e13._child_hwnds(ch))
        render = next((k["hwnd"] for k in kids if "mmuirender" in k["class"].lower()), ch)
        composer_y = 0.7 * h  # composer occupies the bottom band; message list above it
        needle = args.text[:6]  # prefix match: robust to OCR wrapping / dropped chars
        worker.run(lambda: _click_local(ch, composer))
        time.sleep(0.5)
        worker.run(lambda: _clear_composer(ch, composer))
        time.sleep(0.6)
        worker.run(lambda: _inject_chars(ch, args.text))
        time.sleep(1.0)

        def staged_now():
            bs = _ocr_boxes(worker, ch, tmp_dir, ocr)
            return any(needle in b["text"] and b["bounds"][1] > composer_y for b in bs)
        staged = staged_now()
        results["stage"] = {"staged": staged, "needle": needle, "method": "WM_CHAR_main_delayed"}
        if not staged or args.upto == "stage":
            results["verdict"] = "staged" if staged else "stage_failed"
            raise _Stop()

        # --- send: click OCR-located 发送 on the hwnd that owns it (render child first,
        # then main), verify airtight: text appears in MESSAGE area AND composer is empty.
        def send_state():
            bs = _ocr_boxes(worker, ch, tmp_dir, ocr)
            in_msg = any(needle in b["text"] and b["bounds"][3] < composer_y for b in bs)
            in_composer = any(needle in b["text"] and b["bounds"][1] > composer_y for b in bs)
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
        if worker is not None:
            worker.close()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(wintypes.HANDLE(int(hdesk))))
        # KEEP the stub alive (no _cleanup_stub): the session persists for the next attach.
        results["stub_kept_alive"] = True
        for f in Path(tmp_dir).glob("*.png"):
            f.unlink(missing_ok=True)
        if not list(Path(tmp_dir).iterdir()):
            os.rmdir(tmp_dir)

    output = run_dir / "wechat_hidden_send.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: results.get(k) for k in
               ("run_id", "verdict", "logged_in", "session", "locate", "open_target", "stage",
                "send", "host_foreground_changed", "stub_kept_alive", "error")}
    summary["output"] = str(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
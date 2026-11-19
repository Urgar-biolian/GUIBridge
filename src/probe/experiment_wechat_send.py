"""E11 WeChat foreground send demo to 文件传输助手 (one-off, NOT an adapter).

Hidden-desktop WeChat is infeasible (measured E10: single-instance pops host, self-drawn
zero UIA, SendInput no second cursor). With explicit user authorization this demo uses the
FOREGROUND OCR + clipboard path: restore WeChat -> Ctrl+F search 文件传输助手 -> open ->
OCR-verify right-panel title == 文件传输助手 (anti-mis-send gate) -> click input -> clipboard
Ctrl+V stage test text -> OCR verify staged -> [manual confirm] -> Enter send -> OCR verify
bubble. Declared PHYSICAL_INPUT / success_with_interference; fail-stop at any gate, no
auto-retry (principles 6/7). Privacy: private chat/contact text never logged; readable PNG
grabbed outside repo and deleted right after OCR; artifacts gitignored. Leave-as-found.

Modes (--upto): recon (read-only layout) | navigate | stage | send. Default recon.
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
for _p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experiment_wechat_readonly as e10  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from packages.perception.ocr import OCRChannel, grab_window_png  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = wh.user32
kernel32 = wh.kernel32
SW_RESTORE = 9
SW_MINIMIZE = 6
VK_CONTROL, VK_F, VK_V, VK_A = 0x11, 0x46, 0x56, 0x41
VK_RETURN, VK_DELETE = 0x0D, 0x2E
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
TARGET = "文件传输助手"
DEFAULT_TEXT = "GUIBridge 前台演示测试消息，请忽略。"

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def clipboard_write(text: str) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise RuntimeError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def combo(vk: int) -> None:
    wh._send_key(VK_CONTROL)
    wh._send_key(vk)
    wh._send_key(vk, up=True)
    wh._send_key(VK_CONTROL, up=True)


def enter() -> None:
    wh._send_key(VK_RETURN)
    wh._send_key(VK_RETURN, up=True)


def force_fg(target: int) -> bool:
    """Reliably steal foreground back: attach to BOTH the current foreground thread
    and the target thread (wh.ensure_foreground attaches only to target, which fails
    against another process's foreground lock — e.g. WeChat's CEF window)."""
    target = int(target)
    fg = int(user32.GetForegroundWindow() or 0)
    cur = kernel32.GetCurrentThreadId()
    fg_t = user32.GetWindowThreadProcessId(fg, None)
    tg_t = user32.GetWindowThreadProcessId(target, None)
    a1 = user32.AttachThreadInput(cur, fg_t, True)
    a2 = user32.AttachThreadInput(cur, tg_t, True)
    user32.ShowWindow(target, SW_RESTORE)
    user32.BringWindowToTop(target)
    ok = user32.SetForegroundWindow(target)
    if a1:
        user32.AttachThreadInput(cur, fg_t, False)
    if a2:
        user32.AttachThreadInput(cur, tg_t, False)
    return bool(ok)


def restore_wechat() -> dict:
    info = e10.collect_wechat()
    if not info["pids"] or not info["render_windows"]:
        raise RuntimeError("WeChat not running / no render surface")
    render = max(info["render_windows"], key=lambda r: r["rect"]["area"])
    rh, parent = render["hwnd"], render["parent_hwnd"]
    original_fg = int(user32.GetForegroundWindow() or 0)
    user32.ShowWindow(parent, SW_RESTORE)
    wh.ensure_foreground(parent)
    time.sleep(1.2)
    x, y, w, h = wh.window_rect(rh)
    return {"render_hwnd": rh, "window_id": format(rh, "x"), "restore_hwnd": parent,
            "original_fg": original_fg, "rect": (x, y, w, h),
            "on_screen": x >= -10000 and y >= -10000 and w > 1 and h > 1}


def ocr_boxes(window_id: str, tmp_dir: str, ocr: OCRChannel) -> list[dict]:
    png = grab_window_png(window_id, out_dir=tmp_dir)
    try:
        return ocr.read_text_boxes(png)
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def _nav_redact(boxes: list[dict], rect: tuple) -> dict:
    """Layout summary; redact private chat/contact text, keep nav labels + bounds."""
    x, y, w, h = rect
    keep = ("文件传输助手", "搜索", "发送", "输入", "微信", "搜一搜")
    out = {"total_boxes": len(boxes), "target_hits": [], "search_hits": [],
           "send_hits": [], "top_region": [], "input_region": []}
    for b in boxes:
        x1, y1, x2, y2 = b["bounds"]
        t = b["text"]
        if TARGET in t:
            out["target_hits"].append({"bounds": b["bounds"], "text": t})
        if "搜索" in t or "搜一搜" in t:
            out["search_hits"].append({"bounds": b["bounds"], "text": t})
        if "发送" in t:
            out["send_hits"].append({"bounds": b["bounds"], "text": t})
        if y2 < 90:
            out["top_region"].append({"bounds": b["bounds"],
                                      "text": t if any(k in t for k in keep) else f"<redacted len={len(t)}>"})
        if y1 > h - 200:
            out["input_region"].append({"bounds": b["bounds"],
                                        "text": t if any(k in t for k in keep) else f"<redacted len={len(t)}>"})
    return out


def click_rel(state: dict, rx: int, ry: int) -> None:
    x, y, _, _ = state["rect"]
    wh.click_at(x + rx, y + ry)


def _center(b: dict) -> tuple[int, int]:
    x1, y1, x2, y2 = b["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2


def _find(boxes: list[dict], needle: str) -> list[dict]:
    return [b for b in boxes if needle in b["text"]]


def navigate(state: dict, ocr: OCRChannel, tmp_dir: str, results: dict) -> bool:
    """Search 文件传输助手, open it, OCR-verify right-panel title. Fail-stop gate."""
    boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
    search = _find(boxes, "搜索")
    if search:
        cx, cy = _center(search[0])
        click_rel(state, cx, cy)
    else:
        combo(VK_F)
    time.sleep(0.6)
    clipboard_write(TARGET)
    combo(VK_V)
    time.sleep(1.2)
    boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
    hits = _find(boxes, TARGET)
    results["search_target_hits"] = [
        {"bounds": b["bounds"], "text": b["text"] if b["text"].strip() == TARGET else "<redacted>"}
        for b in hits]
    # Clean exact-match contact result rows below the search input echo; topmost first.
    # Excludes 聊天记录 rows (private contact names) and the bottom 搜一搜 footer.
    rows = [b for b in hits if b["text"].strip() == TARGET and b["bounds"][1] > 100]
    rows.sort(key=lambda b: b["bounds"][1])
    if not rows:
        results["gate"] = "no_search_result_row"
        return False
    cx, cy = _center(rows[0])
    click_rel(state, cx, cy)
    time.sleep(1.2)
    boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
    # Right-panel title: top region (y2 < 90), right of sidebar (x1 > 340).
    title = [b for b in boxes if b["bounds"][3] < 90 and b["bounds"][0] > 340]
    results["title_region"] = [{"bounds": b["bounds"],
                                "text": b["text"] if TARGET in b["text"] else "<redacted>"} for b in title]
    verified = any(TARGET in b["text"] for b in title)
    results["title_verified_target"] = verified
    if not verified:
        results["gate"] = "title_not_target"
        return False
    return True


def stage_text(state: dict, ocr: OCRChannel, tmp_dir: str, text: str, results: dict) -> bool:
    """Click input box, clear draft, clipboard-paste test text, OCR-verify staged."""
    rx, ry, rw, rh = state["rect"]
    click_rel(state, int(rw * 0.55), rh - 75)  # right-panel input area, bottom center
    time.sleep(0.4)
    combo(VK_A)
    wh._send_key(VK_DELETE)
    wh._send_key(VK_DELETE, up=True)
    clipboard_write(text)
    combo(VK_V)
    time.sleep(0.8)
    boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
    staged = [b for b in boxes if text[:8] in b["text"]]
    results["staged_hits"] = [{"bounds": b["bounds"], "text": b["text"]} for b in staged]
    results["text_staged_verified"] = bool(staged)
    if not staged:
        results["gate"] = "text_not_staged"
        return False
    return True


def do_send(state: dict, ocr: OCRChannel, tmp_dir: str, text: str, results: dict) -> dict:
    """Click 发送 button, OCR-verify sent bubble. FocusGuard-wrapped foreground input."""
    guard = Win32FocusGuard(state["render_hwnd"])

    def action():
        boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
        send = _find(boxes, "发送")
        if not send:
            raise RuntimeError("send button not located")
        cx, cy = _center(send[0])
        click_rel(state, cx, cy)
        time.sleep(1.0)
        after = ocr_boxes(state["window_id"], tmp_dir, ocr)
        bubble = [b for b in after if text[:8] in b["text"]]
        return {"send_button": send[0]["bounds"],
                "bubble_verified": bool(bubble),
                "bubble_hits": [{"bounds": b["bounds"], "text": b["text"]} for b in bubble]}

    run = guard.wrap_with_events(action)
    res = run.result
    results["send"] = res
    results["send_interference"] = {
        "cursor_displacement": run.cursor_displacement,
        "unexpected_focus_switch": run.unexpected_focus_switch,
        "external_input_during_window": run.external_input_during_window,
        "event_hook_active": run.event_hook_active,
    }
    verified = res["bubble_verified"]
    results["effect_verified"] = verified
    results["state"] = ("success_with_interference" if verified else "unconfirmed")
    results["risk"] = "physical_input"
    results["channel"] = "foreground_input"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", choices=["recon", "navigate", "stage", "send"], default="recon")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    args = ap.parse_args()
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="gb_wxsend_")
    ocr = OCRChannel()
    results = {"run_id": run_id, "mode": args.upto, "target": TARGET, "test_text": args.text}
    state = None
    try:
        state = restore_wechat()
        results["restore"] = {k: state[k] for k in ("render_hwnd", "rect", "on_screen", "original_fg")}
        if not state["on_screen"]:
            results["verdict"] = "restore_did_not_surface"
        else:
            boxes = ocr_boxes(state["window_id"], tmp_dir, ocr)
            results["recon"] = _nav_redact(boxes, state["rect"])
            if args.upto == "recon":
                results["verdict"] = "recon_observed"
            elif not navigate(state, ocr, tmp_dir, results):
                results["verdict"] = "navigate_gate_failed"
            elif args.upto == "navigate":
                results["verdict"] = "navigated_target_verified"
            elif not stage_text(state, ocr, tmp_dir, args.text, results):
                results["verdict"] = "stage_gate_failed"
            elif args.upto == "stage":
                results["verdict"] = "text_staged_awaiting_send_confirm"
            else:
                do_send(state, ocr, tmp_dir, args.text, results)
                results["verdict"] = "send_attempted"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        if state:
            try:
                user32.ShowWindow(state["restore_hwnd"], SW_MINIMIZE)
                time.sleep(0.8)
                ofg = state["original_fg"]
                if ofg and user32.IsWindowVisible(ofg):
                    force_fg(ofg)
                time.sleep(0.3)
                results["cleanup"] = {"reminimized": True,
                                      "foreground_returned_to": int(user32.GetForegroundWindow() or 0)}
            except Exception as exc:  # noqa: BLE001
                results["cleanup"] = {"error": repr(exc)}
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
    output = run_dir / "wechat_send.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "mode": args.upto, "verdict": results.get("verdict"),
                      "output": str(output), "gate": results.get("gate"),
                      "title_verified_target": results.get("title_verified_target"),
                      "text_staged_verified": results.get("text_staged_verified"),
                      "search_target_hits": results.get("search_target_hits"),
                      "staged_hits": results.get("staged_hits"),
                      "effect_verified": results.get("effect_verified"),
                      "state": results.get("state"),
                      "send_interference": results.get("send_interference"),
                      "cleanup": results.get("cleanup"), "error": results.get("error")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""E13b hidden-desktop WeChat "switch account" reconnaissance (NO login, NO send).

E13 showed the hidden second instance's login screen is a SAVED-ACCOUNT enter screen
(avatar + 进入微信), not a QR. The saved account is the HOST account (user-confirmed), so
clicking 进入微信 would kick the host session (same-account single-PC limit) — forbidden.
To reach the SECOND account we must click 切换账号 (switch account). This probe clicks ONLY
that navigation control on the hidden desktop (a non-destructive login-navigation click,
authorized by the user's virtual-desktop direction), then captures + UIA-scans the resulting
screen to learn whether it is a QR (user scans with second account) or an account list.

Hidden desktop cannot receive SendInput (E8), so the click uses worker UIA InvokePattern or
PostMessage WM_LBUTTONDOWN/UP at the control rect. Login-screen UI labels (切换账号/进入微信)
are benign navigation text, not private chat; Name is read ONLY to locate these login controls.
No message is sent, no account is logged in. Cleanup terminates only the stub tree.
"""

from __future__ import annotations

import ctypes
import datetime
import hashlib
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

import uiautomation as auto  # noqa: E402

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_real_app_hidden as e9  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
WECHAT_EXE = e13.WECHAT_EXE
user32 = e8.user32
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
NEEDLE = "切换账号"


def _find_login_control(hwnd: int, needle: str) -> dict:
    """Locate a login-screen navigation control by benign UI label; report Invoke availability."""
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "error": repr(exc)}
    hit: dict = {}

    def walk(control, depth):
        nonlocal hit
        if depth > 8 or hit:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for child in children:
            try:
                name = (child.Name or "").strip()
                if needle in name:
                    r = child.BoundingRectangle
                    has_invoke = False
                    try:
                        has_invoke = child.GetInvokePattern() is not None
                    except Exception:  # noqa: BLE001
                        has_invoke = False
                    hit = {"found": True, "name": name, "role": child.ControlTypeName,
                           "class": child.ClassName, "has_invoke": has_invoke,
                           "rect": [r.left, r.top, r.right, r.bottom]}
                    return
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    walk(window, 0)
    return hit or {"found": False}


def _invoke_uia(hwnd: int, ctl: dict) -> dict:
    window = auto.ControlFromHandle(hwnd)
    target = {}

    def walk(c, d):
        nonlocal target
        if d > 8 or target:
            return
        for ch in c.GetChildren():
            if (ch.Name or "").strip() == ctl["name"]:
                target = {"c": ch}
                return
            walk(ch, d + 1)
    walk(window, 0)
    if not target:
        return {"method": "uia_invoke", "ok": False, "error": "control vanished"}
    pat = target["c"].GetInvokePattern()
    if pat is None:
        return {"method": "uia_invoke", "ok": False, "error": "no invoke pattern"}
    pat.Invoke()
    return {"method": "uia_invoke", "ok": True}


def _postmessage_click(hwnd: int, ctl: dict) -> dict:
    x1, y1, x2, y2 = ctl["rect"]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    wx, wy, _, _ = wh.window_rect(hwnd)
    lx, ly = cx - wx, cy - wy
    lp = (ly << 16) | (lx & 0xFFFF)
    user32.PostMessageW(wintypes.HWND(int(hwnd)), WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(wintypes.HWND(int(hwnd)), WM_LBUTTONUP, 0, lp)
    return {"method": "postmessage_coords", "ok": True, "client_xy": [lx, ly]}


def _shoot_hash(worker, hwnd: int, path: str) -> str:
    worker.run(lambda: e13._capture_png(hwnd, path))
    if not os.path.exists(path):
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBWxSwitch_{run_id}"
    tmp_dir = tempfile.mkdtemp(prefix="gb_wxswitch_")
    png_path = os.path.join(tmp_dir, "wechat_switch_screen.png")
    results: dict = {"run_id": run_id, "desktop": desktop, "mode": "switch_account_recon_no_login"}
    hdesk = 0
    worker = None
    launch: dict = {}
    host_fg_before = int(user32.GetForegroundWindow() or 0)
    try:
        hdesk = user32.CreateDesktopW(desktop, None, None, 0, e8.GENERIC_ALL, None)
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())
        worker = e8.DesktopWorker(int(hdesk))
        launch = e9._launch_real(WECHAT_EXE, desktop)
        results["launch"] = {k: launch.get(k) for k in ("ok", "pid", "error")}
        if not launch.get("ok"):
            raise RuntimeError("launch failed")
        # wait for login (saved-account) window
        login = None
        for _ in range(20):
            mains = e13._qt_mains(worker)
            small = [m for m in mains if m["rect"][2] < 600]
            if small:
                login = max(small, key=lambda m: m["area"])
                break
            time.sleep(1.0)
        if login is None:
            results["verdict"] = "no_login_window"
            raise RuntimeError("no login window")
        results["login_window"] = login
        lh = login["hwnd"]
        ctl = {"found": False}
        for _ in range(15):
            mains = e13._qt_mains(worker)
            small = [m for m in mains if m["rect"][2] < 600]
            if small:
                lh = max(small, key=lambda m: m["area"])["hwnd"]
            ctl = worker.run(lambda h=lh: _find_login_control(h, NEEDLE))
            if ctl.get("found"):
                break
            time.sleep(1.0)
        results["switch_control"] = ctl
        results["login_window_resolved"] = {"hwnd": lh}
        if not ctl.get("found"):
            results["verdict"] = "switch_control_not_found"
            raise RuntimeError("switch control not found")
        before_hash = _shoot_hash(worker, lh, png_path)
        attempts = []
        changed_by = None
        for fn in (_invoke_uia, _postmessage_click):
            click = worker.run(lambda f=fn: f(lh, ctl))
            time.sleep(2.0)
            after_hash = _shoot_hash(worker, lh, png_path)
            changed = bool(after_hash) and after_hash != before_hash
            attempts.append({**click, "screen_changed": changed, "hash_after": after_hash})
            if changed:
                changed_by = click["method"]
                break
            before_hash = after_hash or before_hash
        results["click_attempts"] = attempts
        results["changed_by"] = changed_by
        time.sleep(1.0)
        mains = e13._qt_mains(worker)
        target = max(mains, key=lambda m: m["area"]) if mains else login
        results["post_switch_window"] = target
        th = target["hwnd"]
        results["post_switch_uia"] = worker.run(lambda: e13._deep_uia(th))
        cap = worker.run(lambda: e13._capture_png(th, png_path))
        results["post_switch_capture"] = cap
        if cap.get("ok") and os.path.exists(png_path):
            os.startfile(png_path)  # noqa: S606
            print(f"SWITCH_SCREEN path={png_path}", flush=True)
        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results["host_fg_after"] != host_fg_before
        results["verdict"] = "switch_screen_captured"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        if launch.get("ok"):
            results["cleanup_stub"] = e13._cleanup_stub(launch["pid"])
        results["cleanup_viewer"] = e13._close_qr_viewer(os.path.basename(png_path))
        # PNG retained for operator read-then-manual-delete (login image, outside repo).
        results["switch_screen_png"] = png_path if os.path.exists(png_path) else None
        if worker:
            worker.close()
        if hdesk:
            closed = False
            for _ in range(3):
                time.sleep(0.3)
                closed = bool(user32.CloseDesktop(hdesk))
                if closed:
                    break
            results["closedesktop_ok"] = closed
    output = run_dir / "wechat_switch_recon.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "output": str(output), "verdict": results.get("verdict"),
                      "switch_control": results.get("switch_control"),
                      "click_attempts": results.get("click_attempts"),
                      "changed_by": results.get("changed_by"),
                      "post_switch_window": results.get("post_switch_window"),
                      "post_switch_uia_nodes": results.get("post_switch_uia", {}).get("node_count"),
                      "host_foreground_changed": results.get("host_foreground_changed"),
                      "cleanup_stub_alive": results.get("cleanup_stub", {}).get("stub_alive"),
                      "error": results.get("error")}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
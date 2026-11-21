"""E13 hidden-desktop WeChat SECOND-ACCOUNT login + post-login control feasibility.

User has a SECOND WeChat account, so logging into a hidden-desktop second instance does
NOT kick the host session (the single-PC login limit is per-account). E12 proved the second
instance launches on a hidden desktop with HOST ZERO interference and shows a login QR
window. This probe:

  1. Launches WeChat on a hidden desktop (CreateProcessW lpDesktop) via a DesktopWorker.
  2. The second instance first shows a SAVED-ACCOUNT enter screen (host account). Clicking
     进入微信 would kick the host session, so the probe instead PostMessage-clicks 切换账号
     (E13b: UIA Invoke is a no-op on self-drawn mmui::XButton; PostMessage mouse coords work)
     to reach the QR, captures it with worker PrintWindow -> PNG (outside repo), opens it on
     the host for the user to scan with their SECOND account. No SwitchDesktop (host desktop
     never replaced; the QR viewer is the only intentional host popup).
  3. Polls for login completion (login window 368x484 -> logged-in chat main window grows).
  4. After login, READ-ONLY feasibility inspection: deep UIA tree of the chat main window
     and render child (ControlTypeName + ClassName + AutomationId + rect, NO Name values —
     private chat/contact text never collected), PrintWindow PIXEL STATISTICS only (no
     readable chat image persisted), child HWND/class enumeration. Determines whether a
     UIA-addressable input composer / send button exists (E8 showed hidden-desktop UIA ops
     are host-zero-interference) or the chat stays self-drawn zero-node (E10 wall).
  5. Cleanup: terminate ONLY the launched stub process TREE (taskkill /T + ancestor-chain
     verification), never the user's host WeChat tree; close desktop; remove QR PNG.

NO message is sent, no input is injected into the chat. Raw JSON -> var/experiments/<run_id>/
wechat_hidden_login.json (gitignored). Provisional isolation label "hidden_desktop"; the
frozen Channel enum and capability table are NOT modified.
"""

from __future__ import annotations

import ctypes
import datetime
import hashlib
import json
import os
import subprocess
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
import experiment_wechat_readonly as e10  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
WECHAT_EXE = Path(r"C:\Program Files\Tencent\Weixin\Weixin.exe")
user32 = e8.user32
gdi32 = e8.gdi32
kernel32 = wh.kernel32
GENERIC_ALL = e8.GENERIC_ALL
PW_RENDERFULLCONTENT = e8.PW_RENDERFULLCONTENT
MAIN_CLASS = "qt51514qwindowicon"
LOGIN_TIMEOUT = 300.0
DIB_RGB_COLORS = 0
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202

gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def _capture_png(hwnd: int, out_path: str) -> dict:
    """Worker-side PrintWindow -> 32bpp DIB -> RGB PNG. Used for the login QR (benign) only."""
    import mss.tools
    _, _, w, h = wh.window_rect(hwnd)
    w, h = max(w, 1), max(h, 1)
    hwnd_dc = user32.GetDC(wintypes.HWND(int(hwnd)))
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    ok = bool(user32.PrintWindow(wintypes.HWND(int(hwnd)), mem_dc, PW_RENDERFULLCONTENT))
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(wintypes.HWND(int(hwnd)), hwnd_dc)
    if got == 0:
        return {"ok": False, "w": w, "h": h, "error": "GetDIBits failed"}
    raw = buf.raw
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        rgb[i * 3] = raw[i * 4 + 2]
        rgb[i * 3 + 1] = raw[i * 4 + 1]
        rgb[i * 3 + 2] = raw[i * 4]
    mss.tools.to_png(bytes(rgb), (w, h), output=out_path)
    return {"ok": ok, "w": w, "h": h, "path": out_path}


def _qt_mains(worker) -> list[dict]:
    def job():
        out = []
        for w in wh.enum_top_level_windows():
            if w["class"].lower() == MAIN_CLASS and e10._process_image(w["pid"]) in ("weixin.exe", "wechatappex.exe"):
                x, y, ww, hh = wh.window_rect(w["hwnd"])
                out.append({"hwnd": w["hwnd"], "pid": w["pid"], "rect": [x, y, ww, hh],
                            "area": max(ww, 0) * max(hh, 0), "title_len": len(w["title"])})
        return out
    return worker.run(job)


def _find_switch_control(hwnd: int, needle: str = "切换账号") -> dict:
    """Locate a benign login-navigation label (enter screen only; QR screen lacks it)."""
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception:  # noqa: BLE001
        return {"found": False}
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
                # Nav targets must be BUTTONS: substring "登录" also appears in the nickname
                # label "当前登录用户XX" (TextControl); clicking that label is a no-op.
                if child.ControlTypeName == "ButtonControl" and needle in (child.Name or ""):
                    r = child.BoundingRectangle
                    hit = {"found": True, "rect": [r.left, r.top, r.right, r.bottom]}
                    return
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    walk(window, 0)
    return hit or {"found": False}


LOGIN_KNOWN_LABELS = {"微信", "进入微信", "登录", "切换账号", "仅传输文件", "扫码登录", ""}
HOST_NICK = "乐乐"


def _login_texts(hwnd: int) -> list:
    """Benign login-screen text labels only (account nickname / nav buttons), never chat."""
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception:  # noqa: BLE001
        return []
    out: list = []

    def walk(control, depth):
        if depth > 8:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for child in children:
            try:
                if child.ControlTypeName == "TextControl":
                    out.append((child.Name or "").strip())
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    walk(window, 0)
    return out


def _click_switch(hwnd: int, rect: list) -> dict:
    """PostMessage mouse at client coords: E13b measured UIA Invoke is a no-op on self-drawn
    mmui::XButton, while PostMessage WM_LBUTTONDOWN/UP DOES activate it on the hidden desktop."""
    x1, y1, x2, y2 = rect
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    wx, wy, _, _ = wh.window_rect(hwnd)
    lx, ly = cx - wx, cy - wy
    lp = (ly << 16) | (lx & 0xFFFF)
    user32.PostMessageW(wintypes.HWND(int(hwnd)), WM_LBUTTONDOWN, 1, lp)
    user32.PostMessageW(wintypes.HWND(int(hwnd)), WM_LBUTTONUP, 0, lp)
    return {"client_xy": [lx, ly]}


def _shoot_hash(worker, hwnd: int, path: str) -> str:
    """Capture -> hash -> immediately delete. Only the hash survives (no readable chat image)."""
    worker.run(lambda: _capture_png(hwnd, path))
    if not os.path.exists(path):
        return ""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    try:
        os.remove(path)
    except OSError:
        pass
    return digest


def _deep_uia(hwnd: int) -> dict:
    """Structural UIA: ControlTypeName + ClassName + AutomationId + rect. NO Name (privacy).
    Lists Edit/Document/Button nodes structurally to judge background-write feasibility."""
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc)}
    nodes: list[tuple] = []
    write_candidates: list[dict] = []

    def walk(control, depth):
        if depth > 8:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for child in children:
            try:
                role = child.ControlTypeName
                cls = child.ClassName
                aid = child.AutomationId
                nodes.append((role, cls))
                if any(k in role for k in ("Edit", "Document", "Button")):
                    try:
                        r = child.BoundingRectangle
                        rect = [r.left, r.top, r.right, r.bottom]
                    except Exception:  # noqa: BLE001
                        rect = None
                    write_candidates.append({"role": role, "class": cls, "automation_id": aid, "rect": rect})
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    try:
        walk(window, 0)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc), "partial_nodes": len(nodes)}
    roles = [n[0] for n in nodes]
    classes = [n[1] for n in nodes]
    return {"available": True, "node_count": len(nodes),
            "has_edit": any("Edit" in r for r in roles),
            "has_button": any("Button" in r for r in roles),
            "has_document": any("Document" in r for r in roles),
            "role_counts": {r: roles.count(r) for r in sorted(set(roles))},
            "class_sample": sorted(set(classes))[:30],
            "write_candidates": write_candidates[:40],
            "name_values_collected": False}


def _click_test(worker, hwnd: int, tabs: list[dict], tmp_dir: str) -> dict:
    """PostMessage click on a UIA-KNOWN tabbar item (navigation only; NO send).
    Must run WHILE the chat chrome is still UIA-exposed: the rich tree is transient."""
    probe_png = os.path.join(tmp_dir, "chat_click_probe.png")
    h0 = _shoot_hash(worker, hwnd, probe_png)
    worker.run(lambda r=tabs[1]["rect"]: _click_switch(hwnd, r))
    time.sleep(1.0)
    h1 = _shoot_hash(worker, hwnd, probe_png)
    worker.run(lambda r=tabs[0]["rect"]: _click_switch(hwnd, r))  # leave-as-found
    time.sleep(0.8)
    h2 = _shoot_hash(worker, hwnd, probe_png)
    return {"target": "main_tabbar_item_2", "rect": tabs[1]["rect"],
            "hwnd": hwnd, "screen_changed_on_click": bool(h1) and h1 != h0,
            "restored_to_first_tab": bool(h2) and h2 != h1,
            "host_fg_during": int(user32.GetForegroundWindow() or 0)}


def _richness_diag(worker, ch: int) -> dict:
    """Why is the settled chat main UIA-poor? Test three mechanisms, all confined to the
    hidden desktop (activation/geometry there cannot touch the host's active desktop)."""
    diag: dict = {}

    def kids_uia():
        return [{"hwnd": k["hwnd"], "class": k["class"],
                 "nodes": _deep_uia(k["hwnd"]).get("node_count", 0)}
                for k in _child_hwnds(ch)]
    diag["children_uia"] = worker.run(kids_uia)

    def activate_read():
        fg_ok = bool(user32.SetForegroundWindow(wintypes.HWND(ch)))
        act = int(user32.SetActiveWindow(wintypes.HWND(ch)) or 0)
        time.sleep(1.5)
        u = _deep_uia(ch)
        return {"set_fg_ok": fg_ok, "set_active_prev": act,
                "nodes": u.get("node_count", 0), "has_button": bool(u.get("has_button")),
                "role_counts": u.get("role_counts"), "uia": u}
    diag["after_activate"] = worker.run(activate_read)

    def resize_read():
        ok = bool(user32.SetWindowPos(wintypes.HWND(ch), None, 721, 320, 800, 600,
                                      0x0001 | 0x0004))  # NOZORDER | NOACTIVATE
        time.sleep(2.0)
        u = _deep_uia(ch)
        return {"set_pos_ok": ok, "rect": list(wh.window_rect(ch)),
                "nodes": u.get("node_count", 0), "has_button": bool(u.get("has_button")),
                "role_counts": u.get("role_counts"), "uia": u}
    diag["after_resize_800x600"] = worker.run(resize_read)
    return diag


def _child_hwnds(hwnd: int) -> list[dict]:
    out: list[dict] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _lp):
        out.append({"hwnd": int(h), "class": wh.window_class(int(h))})
        return True

    user32.EnumChildWindows(wintypes.HWND(int(hwnd)), proc(cb), 0)
    return out[:60]


def _process_tree() -> dict[int, int]:
    class PE32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    pe = PE32W()
    pe.dwSize = ctypes.sizeof(PE32W)
    ppid: dict[int, int] = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        ppid[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
        ok = kernel32.Process32NextW(snap, ctypes.byref(pe))
    kernel32.CloseHandle(snap)
    return ppid


def _is_descendant(pid: int, root: int, ppid: dict[int, int]) -> bool:
    seen = set()
    cur = pid
    while cur and cur not in seen:
        if cur == root:
            return True
        seen.add(cur)
        cur = ppid.get(cur, 0)
    return False


def _cleanup_stub(stub_pid: int) -> dict:
    """Kill ONLY the launched stub tree; verify by ancestor chain, never the host tree."""
    out: dict = {"stub_pid": stub_pid}
    try:
        r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(stub_pid)],
                           capture_output=True, timeout=15)
        out["taskkill_rc"] = r.returncode
        out["taskkill_msg"] = (r.stdout or r.stderr).decode("gbk", "replace").strip()[:200]
    except Exception as exc:  # noqa: BLE001
        out["taskkill_error"] = repr(exc)
    time.sleep(1.5)
    ppid = _process_tree()
    survivors = [pid for pid in ppid if _is_descendant(pid, stub_pid, ppid)]
    for pid in survivors:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1.0)
    ppid2 = _process_tree()
    out["survivors_after"] = [pid for pid in ppid2 if _is_descendant(pid, stub_pid, ppid2)]
    out["stub_alive"] = stub_pid in ppid2
    return out


def _close_qr_viewer(png_name: str) -> dict:
    closed = []
    for w in wh.enum_top_level_windows():
        if png_name.lower() in w["title"].lower() or "照片" in w["title"] or "photos" in w["title"].lower():
            user32.PostMessageW(wintypes.HWND(int(w["hwnd"])), 0x0010, 0, 0)
            closed.append({"hwnd": w["hwnd"], "title": w["title"][:40]})
    return {"viewer_closed": closed}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBWxLogin_{run_id}"
    tmp_dir = tempfile.mkdtemp(prefix="gb_wxlogin_")
    qr_path = os.path.join(tmp_dir, "wechat_login_qr.png")
    results: dict = {"run_id": run_id, "desktop": desktop, "exe": str(WECHAT_EXE),
                     "mode": "second_account_login_feasibility_no_send"}
    hdesk = 0
    worker = None
    launch: dict = {}
    host_fg_before = int(user32.GetForegroundWindow() or 0)
    host_wechat_before = set(e10.collect_wechat()["pids"])
    results["host_wechat_pids_before"] = sorted(host_wechat_before)
    results["host_fg_before"] = host_fg_before
    try:
        if not WECHAT_EXE.exists():
            results["verdict"] = "exe_not_found"
            raise RuntimeError("WeChat exe not found")
        hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
        results["desktop_created"] = bool(hdesk)
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())
        worker = e8.DesktopWorker(int(hdesk))
        results["worker_desktop_ok"] = worker.desktop_ok
        launch = e9._launch_real(WECHAT_EXE, desktop)
        results["launch"] = {k: launch.get(k) for k in ("ok", "pid", "error")}
        if not launch.get("ok"):
            results["verdict"] = "launch_failed"
            raise RuntimeError("launch failed")
        stub_pid = launch["pid"]

        # Wait for the login QR window, capture it, open on host for the user to scan.
        qr_shown = False
        qr_last = 0.0
        auto_entered = False
        last_state = 0.0
        login_window = None
        deadline = time.time() + LOGIN_TIMEOUT
        logged_in = False
        chat_window = None
        rich_best = None
        rich_timeline: list[dict] = []
        click_done = False
        chat_first_seen = 0.0
        t_start = time.time()
        while time.time() < deadline:
            mains = _qt_mains(worker)
            if mains:
                biggest = max(mains, key=lambda m: m["area"])
                if biggest["rect"][2] < 600:
                    login_window = biggest
                    lh = biggest["hwnd"]
                    texts = worker.run(lambda h=lh: _login_texts(h))
                    results["login_texts"] = texts
                    nick = next((t for t in texts if t not in LOGIN_KNOWN_LABELS), None)
                    if "扫码登录" in texts:
                        # QR screen (fresh, or after 登录 fell back to re-scan): always show it.
                        if not qr_shown:
                            cap = worker.run(lambda h=lh: _capture_png(h, qr_path))
                            results["qr_capture"] = cap
                            if cap.get("ok") and os.path.exists(qr_path):
                                os.startfile(qr_path)  # noqa: S606
                                qr_shown = True
                                qr_last = time.time()
                                print(f"QR_READY path={qr_path}", flush=True)
                                print("请用【第二个微信账户】扫码登录隐藏桌面实例（主机微信不受影响）。", flush=True)
                    elif nick and nick != HOST_NICK and not auto_entered:
                        # Saved SECOND account enter screen: resume WITHOUT a QR scan by
                        # clicking 进入微信 / 登录. Only when nick != host 乐乐.
                        btn = worker.run(lambda h=lh: _find_switch_control(h, "进入微信"))
                        label = "进入微信"
                        if not btn.get("found"):
                            btn = worker.run(lambda h=lh: _find_switch_control(h, "登录"))
                            label = "登录"
                        if btn.get("found"):
                            results["auto_enter"] = {
                                "nick": nick, "button": label,
                                "click": worker.run(lambda h=lh, r=btn["rect"]: _click_switch(h, r)),
                            }
                            auto_entered = True
                            time.sleep(0.1)
                    elif not auto_entered and not qr_shown:
                        # Host-account enter screen: never click 进入微信 for host; switch to QR.
                        switch_clicks = []
                        for _ in range(3):
                            sw = worker.run(lambda h=lh: _find_switch_control(h))
                            if not sw.get("found"):
                                break
                            switch_clicks.append(worker.run(lambda h=lh, r=sw["rect"]: _click_switch(h, r)))
                            time.sleep(1.5)
                        results["switch_clicks"] = switch_clicks
                        cap = worker.run(lambda h=lh: _capture_png(h, qr_path))
                        results["qr_capture"] = cap
                        if cap.get("ok") and os.path.exists(qr_path):
                            os.startfile(qr_path)  # noqa: S606
                            qr_shown = True
                            qr_last = time.time()
                            print(f"QR_READY path={qr_path}", flush=True)
                            print("请用【第二个微信账户】扫码登录隐藏桌面实例（主机微信不受影响）。", flush=True)
                # WeChat auto-refreshes an expired QR inside the hidden window; the host PNG
                # snapshot would go stale. Re-capture + reopen periodically so the user always
                # scans the CURRENT QR.
                if qr_shown and biggest["rect"][2] < 600 and time.time() - qr_last > 40:
                    # Best-effort: the login window can be mid-destruction (user just logged
                    # in); a failed refresh capture must NOT crash the probe.
                    try:
                        _close_qr_viewer(os.path.basename(qr_path))
                        cap = worker.run(lambda h=biggest["hwnd"]: _capture_png(h, qr_path))
                        if cap.get("ok") and os.path.exists(qr_path):
                            os.startfile(qr_path)  # noqa: S606
                            qr_last = time.time()
                            results["qr_refreshes"] = results.get("qr_refreshes", 0) + 1
                            print(f"QR_REFRESHED path={qr_path}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        results["qr_refresh_error"] = repr(exc)
                        qr_last = time.time()
                if auto_entered and not logged_in and time.time() - last_state > 6:
                    last_state = time.time()
                    dbg = os.path.join(tmp_dir, "state.png")
                    try:
                        results["state_windows"] = worker.run(lambda: [
                            {"hwnd": w["hwnd"], "class": w["class"], "visible": w["visible"],
                             "rect": list(wh.window_rect(w["hwnd"]))}
                            for w in wh.enum_top_level_windows()
                            if e10._process_image(w["pid"]) in ("weixin.exe", "wechatappex.exe")])
                        if mains:
                            worker.run(lambda h=biggest["hwnd"]: _capture_png(h, dbg))
                        if os.path.exists(dbg):
                            print(f"STATE path={dbg}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        results["state_error"] = repr(exc)
                chat_candidates = [m for m in mains if m["rect"][2] >= 600 and m["rect"][3] >= 400]
                # The chat chrome (tabbar/titlebar buttons) is UIA-exposed only during a
                # BRIEF post-login stage (~800x600); once the window settles to its restored
                # geometry the tree collapses to the self-drawn render pane. Score every
                # chat-sized window each fast poll and run the click test IN that stage.
                for m in chat_candidates:
                    u = worker.run(lambda h=m["hwnd"]: _deep_uia(h))
                    n = u.get("node_count", 0)
                    rich_timeline.append({"t": round(time.time() - t_start, 1), "hwnd": m["hwnd"],
                                          "rect": m["rect"], "nodes": n,
                                          "has_button": bool(u.get("has_button"))})
                    score = (bool(u.get("has_button")), n)
                    if rich_best is None or score > rich_best[0]:
                        rich_best = (score, m, u)
                    tabs = [c for c in u.get("write_candidates", [])
                            if c["class"] == "mmui::XTabBarItem" and c.get("rect")]
                    if len(tabs) >= 2 and not click_done:
                        click_done = True
                        results["chat_click_test"] = _click_test(worker, m["hwnd"], tabs, tmp_dir)
                        results["chat_click_stage_rect"] = m["rect"]
                if chat_candidates:
                    logged_in = True
                    chat_window = max(chat_candidates, key=lambda m: m["area"])
                    if not chat_first_seen:
                        chat_first_seen = time.time()
                    if click_done or time.time() - chat_first_seen > 10:
                        break
            # Fast polling through the login transition so the transient rich stage is caught.
            time.sleep(0.15 if (auto_entered or qr_shown) and not click_done else 2.0)
        results["login_window"] = login_window
        results["qr_shown"] = qr_shown
        results["logged_in"] = logged_in
        results["host_fg_after_login"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results["host_fg_after_login"] != host_fg_before
        # Attribute any host foreground change: the QR viewer (Photos) popup is intentional;
        # a WeChat/other-app foreground steal would be real interference.
        fg_hwnd = results["host_fg_after_login"]
        fg_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(int(fg_hwnd)), ctypes.byref(fg_pid))
        results["host_fg_after_login_image"] = e10._process_image(int(fg_pid.value))

        if not logged_in:
            results["verdict"] = "login_not_completed_timeout"
        else:
            results["chat_window"] = chat_window
            ch = chat_window["hwnd"]
            results["chat_uia_timeline"] = rich_timeline[:300]
            settled = worker.run(lambda: _deep_uia(ch))
            results["chat_uia_settled"] = settled
            diag = _richness_diag(worker, ch)
            results["chat_uia_diag"] = {
                k: ({kk: vv for kk, vv in v.items() if kk != "uia"} if isinstance(v, dict) else v)
                for k, v in diag.items()}
            for key in ("after_activate", "after_resize_800x600"):
                u = diag.get(key, {}).get("uia") or {}
                if u.get("node_count", 0) > (rich_best[0][1] if rich_best else 0):
                    rich_best = ((bool(u.get("has_button")), u["node_count"]), chat_window, u)
                    results["chat_uia_rich_source"] = key
                tabs = [c for c in u.get("write_candidates", [])
                        if c["class"] == "mmui::XTabBarItem" and c.get("rect")]
                if len(tabs) >= 2 and not click_done:
                    click_done = True
                    results["chat_click_test"] = _click_test(worker, ch, tabs, tmp_dir)
                    results["chat_click_stage"] = key
            if rich_best is not None:
                results["chat_window_rich"] = rich_best[1]
                results["chat_uia"] = rich_best[2]
            else:
                results["chat_uia"] = settled
            results["chat_capture"] = worker.run(lambda: e8._capture_feasibility(ch))
            results["chat_children"] = worker.run(lambda: _child_hwnds(ch))
            renders = [c for c in results["chat_children"] if "mmuirender" in c["class"].lower()]
            results["render_children"] = renders
            if renders:
                rh = renders[0]["hwnd"]
                results["render_uia"] = worker.run(lambda: _deep_uia(rh))
                results["render_capture"] = worker.run(lambda: e8._capture_feasibility(rh))
            uia = results["chat_uia"]
            results["verdict"] = "logged_in_inspected"
            results["write_path_hint"] = (
                "uia_write_candidate" if (uia.get("has_edit") or uia.get("has_document"))
                else "selfdrawn_no_uia_write")
            if not click_done:
                tabs = [c for c in uia.get("write_candidates", [])
                        if c["class"] == "mmui::XTabBarItem" and c.get("rect")]
                if len(tabs) >= 2:
                    results["chat_click_test"] = _click_test(worker, ch, tabs, tmp_dir)
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        if launch.get("ok"):
            results["cleanup_stub"] = _cleanup_stub(launch["pid"])
        if qr_shown:
            results["cleanup_viewer"] = _close_qr_viewer(os.path.basename(qr_path))
        try:
            if os.path.exists(qr_path):
                os.remove(qr_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
        if worker:
            worker.close()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))
        results["host_fg_final"] = int(user32.GetForegroundWindow() or 0)

    output = run_dir / "wechat_hidden_login.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "run_id": run_id, "output": str(output), "verdict": results.get("verdict"),
        "logged_in": results.get("logged_in"), "qr_shown": results.get("qr_shown"),
        "auto_enter": results.get("auto_enter"), "login_texts": results.get("login_texts"),
        "chat_window": results.get("chat_window"),
        "chat_uia_nodes": results.get("chat_uia", {}).get("node_count"),
        "chat_uia_has_edit": results.get("chat_uia", {}).get("has_edit"),
        "chat_uia_has_document": results.get("chat_uia", {}).get("has_document"),
        "chat_uia_has_button": results.get("chat_uia", {}).get("has_button"),
        "write_path_hint": results.get("write_path_hint"),
        "chat_click_test": results.get("chat_click_test"),
        "render_uia_nodes": results.get("render_uia", {}).get("node_count"),
        "chat_capture_ok": results.get("chat_capture", {}).get("capture_ok"),
        "host_foreground_changed": results.get("host_foreground_changed"),
        "host_fg_after_login_image": results.get("host_fg_after_login_image"),
        "cleanup_stub_alive": results.get("cleanup_stub", {}).get("stub_alive"),
        "cleanup_survivors": results.get("cleanup_stub", {}).get("survivors_after"),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""E9 real-app hidden-desktop controlled test: does isolation generalize beyond self-built targets?

Launches benign system apps (Character Map / Notepad / Calculator) as FRESH instances on a
hidden desktop via CreateProcessW(lpDesktop). A hidden-desktop worker thread enumerates the
app window, reads its UIA semantic tree, captures it with PrintWindow, and (for classic edit
controls) performs ONE reversible WM_SETTEXT write (no file save) while host FocusGuard
measures host foreground/cursor. Controlled: only our own fresh instances, no user windows,
no saves, no destructive ops, no Trae/WeChat. Processes terminated after each trial.

Honest negatives expected: Store/UWP apps may ignore lpDesktop (window lands on host or never
appears on the hidden desktop) and DirectComposition windows may PrintWindow blank. Whatever
happens is recorded, not assumed. Raw JSON -> var/experiments/<run_id>/real_app_hidden.json
(gitignored). Provisional isolation label "hidden_desktop"; frozen Channel enum NOT modified.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import sys
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

import uiautomation as auto  # noqa: E402

import experiment_hidden_desktop as e8  # noqa: E402
import postmessage_ops as pm  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

RUNS = ROOT / "var" / "experiments"
SYSTEM32 = Path(r"C:\Windows\System32")
GENERIC_ALL = 0x10000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_TIMEOUT = 0x00000102

user32 = e8.user32
kernel32 = wh.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
    wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.c_void_p, ctypes.c_void_p,
]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def _launch_real(exe: Path, desktop: str) -> dict:
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = f"WinSta0\\{desktop}"
    pi = PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(f'"{exe}"')
    ok = kernel32.CreateProcessW(
        None, cmdline, None, None, False, CREATE_UNICODE_ENVIRONMENT,
        None, None, ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        return {"ok": False, "error": repr(ctypes.WinError(ctypes.get_last_error()))}
    kernel32.CloseHandle(pi.hThread)
    return {"ok": True, "pid": int(pi.dwProcessId), "hprocess": int(pi.hProcess)}


def _terminate(launch: dict, matched_hwnd: int, matched_pid: int) -> None:
    if not launch.get("ok"):
        return
    # UWP/Store: the visible window may belong to a different host pid; close just that
    # window gracefully (never kill a shared ApplicationFrameHost). Classic: force-kill
    # our own fresh instance (no save prompt, nothing persisted).
    if matched_hwnd and matched_pid and matched_pid != launch["pid"]:
        user32.PostMessageW(wintypes.HWND(int(matched_hwnd)), 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(0.6)
    hproc = wintypes.HANDLE(int(launch["hprocess"]))
    kernel32.TerminateProcess(hproc, 0)
    kernel32.WaitForSingleObject(hproc, 3000)
    kernel32.CloseHandle(hproc)


def _hidden_windows(worker) -> list[dict]:
    return worker.run(lambda: wh.enum_top_level_windows())


# TSF/IME/tooltip helper windows share the app pid but are NOT the app's main window;
# matching them yields empty UIA trees and 1x1 captures (false negatives).
_HELPER_CLASSES = {
    "touch tooltip window", "tooltips_class32", "ime", "msctfime ui",
    "cicerouiwndframe", "cicloaderwndclass", "combolbox",
    "uac_inputindicatoroverlaywnd", "uac input indicator", "gdi+ hook window class",
}
_HELPER_TITLES = {
    "tooltip", "default ime", "msctfime ui", "cicerouiwndframe",
    "tf_floatinglangbar_wndtitle",
}


def _is_main_window(w: dict) -> bool:
    return (bool(w["visible"]) and bool(w["title"])
            and w["class"].lower() not in _HELPER_CLASSES
            and w["title"].lower() not in _HELPER_TITLES)


def _match_window(windows: list[dict], pid: int, hints: tuple[str, ...]) -> dict | None:
    mains = [w for w in windows if w["pid"] == pid and _is_main_window(w)]
    for w in mains:
        if any(h in f"{w['title']} {w['class']}".lower() for h in hints):
            return w
    if mains:
        return mains[0]
    for w in windows:
        if any(h in f"{w['title']} {w['class']}".lower() for h in hints) and _is_main_window(w):
            return w
    return None


def _clean_host_popups(app: dict, host_before: set[int]) -> list[dict]:
    """UWP/Store apps may ignore lpDesktop and pop on the HOST desktop. Close just those
    new windows that match the app (graceful WM_CLOSE, never kill a shared host process)."""
    closed = []
    for w in wh.enum_top_level_windows():
        if w["hwnd"] in host_before or not _is_main_window(w):
            continue
        if any(h in f"{w['title']} {w['class']}".lower() for h in app["hints"]):
            user32.PostMessageW(wintypes.HWND(int(w["hwnd"])), 0x0010, 0, 0)  # WM_CLOSE
            closed.append({"hwnd": w["hwnd"], "title": w["title"], "class": w["class"]})
    if closed:
        time.sleep(0.8)
    return closed


def _uia_summary(hwnd: int) -> dict:
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc)}
    nodes: list[tuple] = []

    def walk(control, depth):
        if depth > 4:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for child in children:
            try:
                nodes.append((child.ControlTypeName, child.Name, child.ClassName))
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    try:
        walk(window, 0)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc), "partial_nodes": len(nodes)}
    roles = [n[0] for n in nodes]
    return {
        "available": True,
        "node_count": len(nodes),
        "has_edit": any("Edit" in r for r in roles),
        "has_button": any("Button" in r for r in roles),
        "has_document": any("Document" in r for r in roles),
        "sample": nodes[:12],
    }


def _find_edit_children(hwnd: int) -> list[dict]:
    found: list[dict] = []

    def callback(h, _lparam):
        cls = wh.window_class(int(h))
        if "edit" in cls.lower():
            found.append({"hwnd": int(h), "class": cls})
        return True

    user32.EnumChildWindows(wintypes.HWND(int(hwnd)), WNDENUMPROC(callback), 0)
    return found


def _edit_write_op(worker, hwnd, guard, edits):
    target = edits[0]["hwnd"]
    before = worker.run(lambda: pm.get_text(target))

    def action():
        buf = ctypes.create_unicode_buffer("GBProbe")
        pm.user32.SendMessageW(target, pm.WM_SETTEXT, 0, ctypes.addressof(buf))

    return e8._hidden_measure(
        worker, guard, action, lambda: pm.get_text(target) == "GBProbe",
        lambda: {"value_before": before, "value_after": pm.get_text(target),
                 "edit_class": edits[0]["class"], "expected": "GBProbe"},
        "real_edit_settext",
    )


APPS = [
    {"name": "charmap", "exe": SYSTEM32 / "charmap.exe", "hints": ("character map", "charmap", "字符映射"), "write": True},
    {"name": "notepad", "exe": SYSTEM32 / "notepad.exe", "hints": ("notepad", "记事本"), "write": True},
    {"name": "calc", "exe": SYSTEM32 / "calc.exe", "hints": ("calculator", "计算器", "calc"), "write": False},
]


def test_app(app: dict, desktop: str, hdesk: int, worker) -> dict:
    host_before = {w["hwnd"] for w in wh.enum_top_level_windows()}
    host_fg_before = int(user32.GetForegroundWindow() or 0)
    launch = _launch_real(app["exe"], desktop)
    record = {"app": app["name"], "exe": str(app["exe"]), "launch": {k: v for k, v in launch.items() if k != "hprocess"}}
    if not launch.get("ok"):
        return record
    matched = None
    try:
        time.sleep(3.0)
        hidden_windows = _hidden_windows(worker)
        record["hidden_window_count"] = len(hidden_windows)
        record["hidden_windows"] = hidden_windows
        matched = _match_window(hidden_windows, launch["pid"], app["hints"])
        host_after = {w["hwnd"] for w in wh.enum_top_level_windows()}
        host_fg_after = int(user32.GetForegroundWindow() or 0)
        record["host_new_windows"] = sorted(host_after - host_before)
        record["host_foreground_changed_on_launch"] = host_fg_after != host_fg_before
        if record["host_new_windows"]:
            record["host_popups_closed"] = _clean_host_popups(app, host_before)
        if matched is None:
            record["matched"] = False
            record["verdict"] = "no_window_on_hidden_desktop"
            return record
        hwnd = matched["hwnd"]
        record["matched"] = True
        record["matched_window"] = matched
        record["matched_pid_is_launched"] = matched["pid"] == launch["pid"]
        record["uia"] = worker.run(lambda: _uia_summary(hwnd))
        record["capture"] = worker.run(lambda: e8._capture_feasibility(hwnd))
        if app["write"]:
            edits = worker.run(lambda: _find_edit_children(hwnd))
            record["edit_children"] = edits
            if edits:
                neutral = wh.find_neutral_window({hwnd})
                wh.ensure_foreground(neutral)
                time.sleep(0.2)
                wh.wait_for_quiescence()
                guard = Win32FocusGuard(neutral)
                record["write_op"] = _edit_write_op(worker, hwnd, guard, edits)
            else:
                record["write_op"] = {"skipped": "no Win32 Edit child (UWP/DirectComposition?)"}
        record["verdict"] = "window_on_hidden_desktop"
        return record
    finally:
        _terminate(launch, matched["hwnd"] if matched else 0, matched["pid"] if matched else 0)


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBReal_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results = {"run_id": run_id, "desktop": desktop, "createdesktop_ok": bool(hdesk), "apps": []}
    worker = None
    try:
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())
        worker = e8.DesktopWorker(int(hdesk))
        results["worker_desktop_ok"] = worker.desktop_ok
        selected = [a for a in APPS if not sys.argv[1:] or a["name"] in sys.argv[1:]]
        results["selected_apps"] = [a["name"] for a in selected]
        for app in selected:
            try:
                results["apps"].append(test_app(app, desktop, int(hdesk), worker))
            except Exception as exc:  # noqa: BLE001
                results["apps"].append({"app": app["name"], "error": repr(exc),
                                        "traceback": traceback.format_exc()})
            time.sleep(1.0)
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        if worker:
            worker.close()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))

    output = run_dir / "real_app_hidden.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {"run_id": run_id, "output": str(output),
               "createdesktop_ok": results["createdesktop_ok"],
               "closedesktop_ok": results.get("closedesktop_ok"), "apps": []}
    for rec in results["apps"]:
        uia = rec.get("uia", {})
        cap = rec.get("capture", {})
        op = rec.get("write_op", {})
        summary["apps"].append({
            "app": rec.get("app"),
            "verdict": rec.get("verdict", rec.get("error")),
            "matched": rec.get("matched"),
            "matched_pid_is_launched": rec.get("matched_pid_is_launched"),
            "host_new_windows": rec.get("host_new_windows"),
            "host_popups_closed": rec.get("host_popups_closed"),
            "host_foreground_changed_on_launch": rec.get("host_foreground_changed_on_launch"),
            "uia_available": uia.get("available"),
            "uia_nodes": uia.get("node_count"),
            "uia_has_edit": uia.get("has_edit"),
            "uia_has_button": uia.get("has_button"),
            "capture_ok": cap.get("capture_ok"),
            "write_state": op.get("state"),
            "write_verified": op.get("effect_verified"),
            "write_host_focus_switch": op.get("evidence", {}).get("unexpected_focus_switch"),
            "write_cursor": op.get("evidence", {}).get("cursor_displacement"),
        })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
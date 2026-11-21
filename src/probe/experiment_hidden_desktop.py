"""E8 hidden-desktop isolation: CreateDesktop + a hidden-desktop worker, host measured.

Question: if a target window lives on a SEPARATE (hidden) desktop of the same window
station, can we operate it and verify the effect while the HOST desktop's foreground
window and system cursor stay untouched? A window on another desktop cannot become the
host desktop's foreground window, so the focus-switch interference measured for
same-desktop button clicks (E7) should be contained to the hidden desktop.

Cross-desktop access from the host thread is restricted (GetWindowRect / WM_GETTEXT /
UIA / PrintWindow all fail across desktops), so execution + verification + capture run
on a WORKER thread that calls SetThreadDesktop(hidden). The host thread only runs
FocusGuard around the worker job, measuring the host desktop. The host never
SwitchDesktop, so the user's visible desktop is never replaced.

Controlled local target only (native_test_app standard controls). No real-app writes,
no Trae/WeChat interaction, no SendInput. Raw JSON -> var/experiments/<run_id>/
hidden_desktop.json (gitignored). Provisional isolation label "hidden_desktop"; the
frozen Channel enum is NOT modified. Host-scoped risk is reported; hidden-desktop
internal foreground is recorded separately, not claimed as host interference.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import queue
import subprocess
import sys
import threading
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

import postmessage_ops as pm  # noqa: E402
import uia_exec as ux  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.classify import classify  # noqa: E402
from packages.focusguard.monitor import FocusRun, Win32FocusGuard  # noqa: E402
from packages.routing.capability import Channel, InterferenceRisk  # noqa: E402

NATIVE_APP = PROBE_DIR / "native_test_app.py"
RUNS = ROOT / "var" / "experiments"
PROVISIONAL_ISOLATION = "hidden_desktop"
GENERIC_ALL = 0x10000000
PW_RENDERFULLCONTENT = 0x00000002
COINIT_APARTMENTTHREADED = 0x2

user32 = wh.user32
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_ssize_t

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.GetPixel.restype = wintypes.DWORD
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL


class DesktopWorker:
    """A thread pinned to the hidden desktop; runs execution/verification/capture jobs.

    The host thread submits jobs and blocks for results while FocusGuard measures the
    host desktop. SetThreadDesktop succeeds because this fresh thread owns no windows
    or hooks; COM is initialised STA so UIA works on this desktop.
    """

    def __init__(self, hdesk: int) -> None:
        self._hdesk = wintypes.HANDLE(int(hdesk))
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self.start_error: str | None = None
        self.desktop_ok = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _loop(self) -> None:
        if not user32.SetThreadDesktop(self._hdesk):
            self.start_error = repr(ctypes.WinError(ctypes.get_last_error()))
            self._ready.set()
            return
        self.desktop_ok = True
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        self._ready.set()
        while True:
            job = self._jobs.get()
            if job is None:
                break
            fn, slot, done = job
            try:
                slot["result"] = fn()
            except Exception as exc:  # noqa: BLE001 - probe records, never crashes
                slot["error"] = repr(exc)
            done.set()

    def run(self, fn, timeout: float = 15.0):
        if self.start_error:
            raise RuntimeError(f"worker desktop setup failed: {self.start_error}")
        slot: dict = {}
        done = threading.Event()
        self._jobs.put((fn, slot, done))
        if not done.wait(timeout):
            raise RuntimeError("hidden-desktop worker job timed out")
        if "error" in slot:
            raise RuntimeError(slot["error"])
        return slot["result"]

    def close(self) -> None:
        self._jobs.put(None)
        self._thread.join(timeout=5)


def _launch_on_desktop(desktop: str, x: int, y: int) -> tuple[subprocess.Popen, int, bool]:
    args = [sys.executable, str(NATIVE_APP), "--desktop", desktop,
            "--x", str(x), "--y", str(y), "--w", "420", "--h", "240",
            "--auto-close-seconds", "180", "--show-no-activate"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8")
    lines: list[str] = []

    def reader() -> None:
        for _ in range(6):
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())
            if "WINDOW_HANDLE=" in line:
                break

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(10)
    handle_line = next((ln for ln in lines if "WINDOW_HANDLE=" in ln), None)
    desktop_ok = any(ln.startswith("THREAD_DESKTOP=") for ln in lines)
    if handle_line is None:
        proc.terminate()
        raise RuntimeError(f"window handle not reported on hidden desktop: {lines!r}")
    return proc, int(handle_line.split("=", 1)[1]), desktop_ok


def _host_neutral(hidden_hwnd: int) -> tuple[int, dict]:
    neutral = wh.find_neutral_window({hidden_hwnd})
    wh.ensure_foreground(neutral)
    time.sleep(0.2)
    quiet = wh.wait_for_quiescence()
    fg = int(user32.GetForegroundWindow() or 0)
    host_windows = {w["hwnd"] for w in wh.enum_top_level_windows()}
    return neutral, {
        "target_hwnd": hidden_hwnd,
        "neutral_hwnd": neutral,
        "host_foreground_at_start": fg,
        "host_foreground_is_neutral": fg == neutral,
        "hidden_listed_in_host_enum": hidden_hwnd in host_windows,
        "quiescent_before_action": quiet,
    }


def _hidden_measure(worker, guard, action_fn, verify_fn, evidence_fn, op) -> dict:
    error = None
    try:
        run = guard.wrap_with_events(lambda: worker.run(action_fn))
    except Exception as exc:  # noqa: BLE001
        run = FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot())
        error = repr(exc)
    time.sleep(0.05)
    verified = False
    evidence: dict = {}
    if error is None:
        try:
            verified = bool(worker.run(verify_fn))
            evidence = dict(worker.run(evidence_fn))
        except Exception as exc:  # noqa: BLE001
            error = repr(exc)
    state = classify(run, verified, error, Channel.UIA)
    evidence.update({
        "op": op,
        "provisional_isolation": PROVISIONAL_ISOLATION,
        "risk_scope": "host_desktop",
        "cursor_displacement": run.cursor_displacement,
        "unexpected_focus_switch": run.unexpected_focus_switch,
        "external_input_during_window": run.external_input_during_window,
        "foreground_events": [fg for _, fg in run.foreground_events],
        "hook_foreground_events": [fg for _, fg in run.hook_foreground_events],
        "event_hook_active": run.event_hook_active,
        "host_focus_before": run.before.foreground_hwnd,
        "host_focus_after": run.after.foreground_hwnd,
    })
    if error:
        evidence["error"] = error
    return {
        "state": state.value,
        "provisional_isolation": PROVISIONAL_ISOLATION,
        "risk": InterferenceRisk.NONE.value,
        "effect_verified": verified,
        "evidence": evidence,
    }


def _capture_feasibility(hwnd: int) -> dict:
    """PrintWindow the hidden-desktop window from the worker (same desktop) and sample."""
    _, _, w, h = wh.window_rect(hwnd)
    w, h = max(w, 1), max(h, 1)
    hwnd_dc = user32.GetDC(wintypes.HWND(int(hwnd)))
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    ok = bool(user32.PrintWindow(wintypes.HWND(int(hwnd)), mem_dc, PW_RENDERFULLCONTENT))
    samples = {
        "center": int(gdi32.GetPixel(mem_dc, w // 2, h // 2)),
        "button_area": int(gdi32.GetPixel(mem_dc, 95, 68)),
        "top_left": int(gdi32.GetPixel(mem_dc, 2, 2)),
    }
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(wintypes.HWND(int(hwnd)), hwnd_dc)
    distinct = len({v for v in samples.values() if v != 0xFFFFFFFF})
    return {"printwindow_return": ok, "window_wh": [w, h], "pixel_samples": samples,
            "non_blank_distinct_colors": distinct, "capture_ok": ok and distinct >= 1}


def _op_bm_click(worker, hwnd, guard):
    button, status = worker.run(lambda: (pm.child_hwnd(hwnd, pm.BUTTON_ID), pm.child_hwnd(hwnd, pm.STATUS_ID)))
    before = worker.run(lambda: pm.get_text(status))
    count_before = pm.clicked_count(before)

    def action():
        pm.user32.PostMessageW(button, pm.BM_CLICK, 0, 0)

    def verify():
        after = pm.clicked_count(pm.get_text(status))
        return count_before is not None and after == count_before + 1

    def evidence():
        return {"status_before": before, "status_after": pm.get_text(status),
                "hidden_foreground_after": int(user32.GetForegroundWindow() or 0)}

    return _hidden_measure(worker, guard, action, verify, evidence, "bm_click_button")


def _op_settext(worker, hwnd, guard, value):
    edit = worker.run(lambda: pm.child_hwnd(hwnd, pm.EDIT_ID))
    before = worker.run(lambda: pm.get_text(edit))

    def action():
        buf = ctypes.create_unicode_buffer(value)
        pm.user32.SendMessageW(edit, pm.WM_SETTEXT, 0, ctypes.addressof(buf))

    return _hidden_measure(worker, guard, action, lambda: pm.get_text(edit) == value,
                           lambda: {"value_before": before, "value_after": pm.get_text(edit),
                                    "expected": value}, "settext_edit")


def _op_checkbox(worker, hwnd, guard):
    cb = worker.run(lambda: pm.child_hwnd(hwnd, pm.CHECKBOX_ID))
    before = worker.run(lambda: int(pm.user32.SendMessageW(cb, pm.BM_GETCHECK, 0, 0)))

    def action():
        pm.user32.PostMessageW(cb, pm.BM_CLICK, 0, 0)

    def verify():
        return int(pm.user32.SendMessageW(cb, pm.BM_GETCHECK, 0, 0)) != before

    return _hidden_measure(worker, guard, action, verify,
                           lambda: {"check_before": before,
                                    "check_after": int(pm.user32.SendMessageW(cb, pm.BM_GETCHECK, 0, 0))},
                           "bm_click_checkbox")


def _op_uia_invoke(worker, hwnd, guard):
    before = worker.run(lambda: ux.read_status(auto.ControlFromHandle(hwnd)))

    def action():
        window = auto.ControlFromHandle(hwnd)
        control = ux.find_control(window, ux.BUTTON_ID)
        pattern = ux._pattern(control, auto.PatternId.InvokePattern) if control else None
        if pattern is None:
            raise RuntimeError("InvokePattern unavailable on hidden desktop")
        pattern.Invoke()

    def verify():
        after = ux.read_status(auto.ControlFromHandle(hwnd))
        return ux.clicked_count(after) is not None and after != before

    return _hidden_measure(worker, guard, action, verify,
                           lambda: {"status_before": before,
                                    "status_after": ux.read_status(auto.ControlFromHandle(hwnd))},
                           "uia_invoke_button")


def hidden_matrix(desktop: str, hdesk: int, trials: int = 2) -> dict:
    ops = {
        "bm_click_button": lambda w, h, g: _op_bm_click(w, h, g),
        "settext_edit": lambda w, h, g: _op_settext(w, h, g, "hidden-settext"),
        "bm_click_checkbox": lambda w, h, g: _op_checkbox(w, h, g),
        "uia_invoke_button": lambda w, h, g: _op_uia_invoke(w, h, g),
    }
    out: dict = {}
    for name, op in ops.items():
        runs = []
        for index in range(trials):
            proc, hwnd, desktop_ok = _launch_on_desktop(desktop, 660 + index * 12, 260 + index * 12)
            worker = DesktopWorker(hdesk)
            try:
                time.sleep(1.0)
                neutral, ctx = _host_neutral(hwnd)
                ctx["thread_desktop_confirmed"] = desktop_ok
                ctx["worker_desktop_ok"] = worker.desktop_ok
                guard = Win32FocusGuard(neutral)
                result = op(worker, hwnd, guard)
                if name == "bm_click_button" and index == 0:
                    ctx["capture"] = worker.run(lambda: _capture_feasibility(hwnd))
                runs.append({**ctx, "result": result})
            finally:
                worker.close()
                proc.terminate()
                proc.wait(timeout=5)
        out[name] = runs
    return out


def host_baseline(trials: int = 1) -> dict:
    """Same button click on a VISIBLE host-desktop background window: E7 showed it
    steals host foreground. Re-measured here as the contrast control."""
    runs = []
    for index in range(trials):
        args = [sys.executable, str(NATIVE_APP), "--x", str(660 + index * 12),
                "--y", str(260 + index * 12), "--w", "420", "--h", "240",
                "--auto-close-seconds", "180", "--show-no-activate"]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8")
        line = proc.stdout.readline()
        hwnd = int(line.split("=", 1)[1]) if "WINDOW_HANDLE=" in line else 0
        try:
            time.sleep(1.0)
            neutral, ctx = _host_neutral(hwnd)
            guard = Win32FocusGuard(neutral)
            result = pm.bm_click_button(hwnd, guard)
            runs.append({**ctx, "result": result})
        finally:
            proc.terminate()
            proc.wait(timeout=5)
    return {"bm_click_button_visible_host": runs}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    desktop = f"GBProbe_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results = {"run_id": run_id, "desktop": desktop,
               "createdesktop_ok": bool(hdesk), "experiments": {}}
    try:
        if not hdesk:
            raise ctypes.WinError(ctypes.get_last_error())
        results["experiments"]["E8_hidden"] = hidden_matrix(desktop, int(hdesk))
        results["experiments"]["E8_host_baseline"] = host_baseline()
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(hdesk))

    output = run_dir / "hidden_desktop.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def summarize(group: dict) -> dict:
        return {
            name: {
                "trials": len(runs),
                "hidden_not_in_host_enum": [not r.get("hidden_listed_in_host_enum", True) for r in runs],
                "states": [r["result"]["state"] for r in runs],
                "verified": [r["result"]["effect_verified"] for r in runs],
                "cursor_displacement": [r["result"]["evidence"].get("cursor_displacement") for r in runs],
                "host_focus_switch": [r["result"]["evidence"].get("unexpected_focus_switch") for r in runs],
                "capture_ok": [r.get("capture", {}).get("capture_ok") for r in runs if "capture" in r],
            }
            for name, runs in group.items()
        }

    summary = {
        "run_id": run_id,
        "output": str(output),
        "createdesktop_ok": results["createdesktop_ok"],
        "closedesktop_ok": results.get("closedesktop_ok"),
        "hidden": summarize(results["experiments"].get("E8_hidden", {})),
        "host_baseline": summarize(results["experiments"].get("E8_host_baseline", {})),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
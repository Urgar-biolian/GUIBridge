"""E12 diagnostic: empirically pinpoint where hidden-desktop WeChat control is blocked.

E10 concluded hidden-desktop WeChat is infeasible, but wall #1 (single-instance handoff)
was INFERRED, not directly launched. This probe turns it into a measurement: it launches
WeChat via CreateProcessW(lpDesktop=hidden) and observes
  (1) does the new process hand off to the running single instance and exit quickly?
  (2) does ANY WeChat window appear on the hidden desktop (pinned-worker enum)?
  (3) does the HOST WeChat window pop on-screen / steal foreground (handoff side effect)?

Recoverable cleanup: terminate ONLY our launched process stub (never the user's running
WeChat pid), minimize host WeChat, force_fg back to the user's window, destroy the desktop.
Read-only intent: no send/click/input on WeChat. Raw JSON -> var/experiments (gitignored).
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
for _p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_real_app_hidden as e9  # noqa: E402
import experiment_wechat_readonly as e10  # noqa: E402
import experiment_wechat_send as e11  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = wh.user32
kernel32 = wh.kernel32
WECHAT_EXE = Path(r"C:\Program Files\Tencent\Weixin\Weixin.exe")
SW_MINIMIZE = 6
WAIT_OBJECT_0 = 0
STILL_ACTIVE = 259

kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL


def _render_offscreen(info: dict) -> bool | None:
    if not info["render_windows"]:
        return None
    r = max(info["render_windows"], key=lambda x: x["rect"]["area"])
    return r["rect"]["off_screen"]


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"run_id": run_id, "exe": str(WECHAT_EXE), "exe_exists": WECHAT_EXE.exists()}
    desktop = f"GBWxDiag_{run_id}"
    hdesk = 0
    worker = None
    launch = {}
    host_fg_before = int(user32.GetForegroundWindow() or 0)
    try:
        before = e10.collect_wechat()
        results["wechat_running_pids"] = before["pids"]
        results["render_offscreen_before"] = _render_offscreen(before)
        results["host_fg_before"] = host_fg_before
        if not WECHAT_EXE.exists():
            results["verdict"] = "exe_not_found"
        else:
            hdesk = user32.CreateDesktopW(desktop, None, None, 0, e8.GENERIC_ALL, None)
            results["desktop_created"] = bool(hdesk)
            if not hdesk:
                results["verdict"] = "desktop_create_failed"
            else:
                worker = e8.DesktopWorker(int(hdesk))
                launch = e9._launch_real(WECHAT_EXE, desktop)
                results["launch"] = {k: launch.get(k) for k in ("ok", "pid", "error")}
                # Poll over ~12s: WeChat's real main window class is Qt51514QWindowIcon
                # (same as host). UAC/IME/Chrome helpers are NOT main UI.
                main_class = "qt51514qwindowicon"
                timeline = []
                main_window = None
                for t in (1.0, 3.0, 6.0, 9.0, 12.0):
                    time.sleep(t if t == 1.0 else t - timeline[-1]["t"])
                    hidden = worker.run(lambda: wh.enum_top_level_windows())
                    hw = [w for w in hidden
                          if e10._process_image(w["pid"]) in ("weixin.exe", "wechatappex.exe")]
                    mains = [w for w in hw if w["class"].lower() == main_class]
                    timeline.append({"t": t, "hidden_total": len(hidden),
                                     "wechat_windows": len(hw),
                                     "qt_main_candidates": [
                                         {"hwnd": w["hwnd"], "class": w["class"],
                                          "title_len": len(w["title"]), "visible": w["visible"]}
                                         for w in mains]})
                    if mains and main_window is None:
                        main_window = mains[0]
                results["timeline"] = timeline
                results["main_window_ever_appeared"] = main_window is not None
                if main_window is not None:
                    mh = main_window["hwnd"]

                    def _rect():
                        r = wintypes.RECT()
                        user32.GetWindowRect(wintypes.HWND(int(mh)), ctypes.byref(r))
                        return [r.left, r.top, r.right, r.bottom]

                    results["main_window"] = {"hwnd": mh, "class": main_window["class"],
                                              "title_len": len(main_window["title"]),
                                              "rect": worker.run(_rect)}
                    results["main_uia"] = worker.run(lambda: e10.uia_structure(mh))
                    results["main_capture"] = worker.run(lambda: e8._capture_feasibility(mh))
                if launch.get("ok"):
                    hproc = wintypes.HANDLE(int(launch["hprocess"]))
                    waited = kernel32.WaitForSingleObject(hproc, 0)
                    code = wintypes.DWORD()
                    kernel32.GetExitCodeProcess(hproc, ctypes.byref(code))
                    results["process_exited"] = (waited == WAIT_OBJECT_0)
                    results["exit_code"] = int(code.value)
                    results["process_still_active"] = (int(code.value) == STILL_ACTIVE)
                after = e10.collect_wechat()
                results["render_offscreen_after"] = _render_offscreen(after)
                results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
                results["host_wechat_popped_onscreen"] = (
                    results["render_offscreen_before"] is True
                    and results["render_offscreen_after"] is False)
                results["host_foreground_changed"] = results["host_fg_after"] != host_fg_before
                # Verdict: usable hidden control needs a MAIN UI window on the hidden desktop.
                if main_window is not None:
                    results["verdict"] = "main_ui_on_hidden_desktop"
                elif results.get("process_still_active"):
                    results["verdict"] = "process_alive_helpers_only_no_main_ui"
                else:
                    results["verdict"] = "process_exited_no_main_ui"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        # Terminate ONLY our launched stub (never the user's running WeChat pid).
        if launch.get("ok"):
            try:
                hproc = wintypes.HANDLE(int(launch["hprocess"]))
                kernel32.TerminateProcess(hproc, 0)
                kernel32.WaitForSingleObject(hproc, 3000)
                kernel32.CloseHandle(hproc)
            except Exception as exc:  # noqa: BLE001
                results["stub_cleanup_error"] = repr(exc)
        # Minimize host WeChat + return foreground to the user's window.
        try:
            info = e10.collect_wechat()
            if info["render_windows"]:
                parent = max(info["render_windows"], key=lambda x: x["rect"]["area"])["parent_hwnd"]
                user32.ShowWindow(parent, SW_MINIMIZE)
                time.sleep(0.8)
            if host_fg_before and user32.IsWindowVisible(host_fg_before):
                e11.force_fg(host_fg_before)
            time.sleep(0.3)
            results["cleanup_fg"] = int(user32.GetForegroundWindow() or 0)
        except Exception as exc:  # noqa: BLE001
            results["cleanup_error"] = repr(exc)
        if worker:
            worker.close()
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(int(hdesk)))
    output = run_dir / "wechat_hidden_diag.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in (
        "run_id", "verdict", "launch", "process_exited_within_3s", "exit_code",
        "hidden_wechat_window_count", "host_wechat_popped_onscreen", "host_foreground_changed",
        "render_offscreen_before", "render_offscreen_after", "cleanup_fg", "closedesktop_ok", "error")},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
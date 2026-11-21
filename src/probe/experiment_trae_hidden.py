"""E17: can a SECOND Trae instance run fully on a hidden desktop, CDP-reachable, read-only?

Feasibility probe for the "independent AI coding workbench" vision. Launches Trae with a
SEPARATE --user-data-dir (fresh empty profile, outside the host profile) and a DIFFERENT
--remote-debugging-port on a hidden desktop (CreateProcessW si.lpDesktop), so the host
Trae single-instance lock/profile is never touched. Measures:

  * second instance launches on the hidden desktop (window appears via worker enum),
  * CDP loopback reachable on the new port from the host (desktop-independent),
  * read-only DOM read (title / chat-root presence / text length) — NO send, NO clicks,
    NO mode switch (live Trae probes are read-only by default),
  * host foreground / cursor unchanged, host Trae window count unchanged.

A fresh profile is logged OUT, so the chat root may be absent (login wall) — that is
reported honestly, not faked. Cleanup force-kills ONLY our own fresh second-instance tree
(distinct pid from host) and closes the desktop. Raw JSON -> var/experiments (gitignored).
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import shutil
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
import experiment_real_app_hidden as e9  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402
import win32_helpers as wh  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = e8.user32
kernel32 = e9.kernel32
GENERIC_ALL = e8.GENERIC_ALL
TRAE_EXE = Path(r"D:\Program\Trae\Trae.exe")
READ_SCRIPT = PROBE_DIR / "cdp_port_read.mjs"


def _launch_trae(desktop: str, profile: str, port: int, project: str | None) -> dict:
    si = e9.STARTUPINFOW()
    si.cb = ctypes.sizeof(e9.STARTUPINFOW)
    si.lpDesktop = f"WinSta0\\{desktop}"
    pi = e9.PROCESS_INFORMATION()
    cmd = (f'"{TRAE_EXE}" --user-data-dir="{profile}" --remote-debugging-port={port} '
           f'--force-renderer-accessibility --new-window')
    if project:
        cmd += f' "{project}"'
    cmdline = ctypes.create_unicode_buffer(cmd)
    ok = kernel32.CreateProcessW(None, cmdline, None, None, False,
                                 e9.CREATE_UNICODE_ENVIRONMENT, None, None,
                                 ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        return {"ok": False, "error": repr(ctypes.WinError(ctypes.get_last_error()))}
    kernel32.CloseHandle(pi.hThread)
    return {"ok": True, "pid": int(pi.dwProcessId), "hprocess": int(pi.hProcess)}


def _descendants(root: int) -> set[int]:
    ppid = e13._process_tree()
    out = {root}
    changed = True
    while changed:
        changed = False
        for pid, parent in ppid.items():
            if parent in out and pid not in out:
                out.add(pid)
                changed = True
    return out


def _host_trae_windows() -> list[int]:
    return [w["hwnd"] for w in wh.enum_top_level_windows()
            if w["visible"] and "trae" in w["title"].lower()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--project", default=r"D:\QoderTest\guibridge-demo-workspace")
    args = ap.parse_args()

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    profile = str(run_dir / "trae_profile")
    desktop = f"GBTrae_{run_id}"
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    results: dict = {"run_id": run_id, "port": args.port, "trae_exe": str(TRAE_EXE),
                     "createdesktop_ok": bool(hdesk), "exe_exists": TRAE_EXE.exists()}
    launch = None
    worker = None
    node = shutil.which("node")
    try:
        fg0 = int(user32.GetForegroundWindow() or 0)
        cur0 = wh.cursor_pos()
        host_wins0 = _host_trae_windows()
        results["host_fg_before"] = fg0
        results["host_trae_windows_before"] = len(host_wins0)
        project = args.project if Path(args.project).exists() else None
        results["project_opened"] = project
        launch = _launch_trae(desktop, profile, args.port, project)
        results["launch"] = {k: launch.get(k) for k in ("ok", "pid", "error")}
        if not launch.get("ok"):
            results["verdict"] = "launch_failed"
            raise RuntimeError(launch.get("error"))
        worker = e8.DesktopWorker(int(hdesk))
        pid = launch["pid"]

        hidden_win = None
        cdp_ok = False
        cdp_payload = None
        diag = []
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            tree = _descendants(pid)

            def _enum(tree=tree):
                out = []
                for w in wh.enum_top_level_windows():
                    if w["pid"] in tree:
                        r = wh.window_rect(w["hwnd"])
                        out.append({"hwnd": w["hwnd"], "pid": w["pid"], "visible": w["visible"],
                                    "rect": list(r), "title_len": len(w["title"]),
                                    "class": w["class"]})
                return out
            all_wins = worker.run(_enum)
            diag = all_wins
            cand = [w for w in all_wins if w["visible"] and w["rect"][2] > 100 and w["rect"][3] > 100]
            if cand and hidden_win is None:
                cand.sort(key=lambda w: w["rect"][2] * w["rect"][3], reverse=True)
                hidden_win = cand[0]
                results["hidden_window"] = {k: hidden_win[k] for k in
                                            ("hwnd", "pid", "rect", "title_len", "class")}
            if node:
                pr = subprocess.run([node, str(READ_SCRIPT), str(args.port)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
                try:
                    payload = json.loads(pr.stdout.strip())
                except json.JSONDecodeError:
                    payload = {"ok": False, "raw": pr.stdout.strip()[:200]}
                if payload.get("ok"):
                    cdp_ok = True
                    cdp_payload = payload
            if hidden_win is not None and cdp_ok:
                break
            time.sleep(1.0)
        results["hidden_window_diag"] = diag
        results["hidden_window_found"] = hidden_win is not None
        results["cdp_reachable"] = cdp_ok
        results["cdp_read"] = cdp_payload
        results["host_fg_after"] = int(user32.GetForegroundWindow() or 0)
        results["host_foreground_changed"] = results["host_fg_after"] != fg0
        cx, cy = wh.cursor_pos()
        results["host_cursor_displacement"] = abs(cx - cur0[0]) + abs(cy - cur0[1])
        host_wins1 = _host_trae_windows()
        results["host_trae_windows_after"] = len(host_wins1)
        results["host_trae_window_added"] = len(host_wins1) > len(host_wins0)
        if hidden_win and cdp_ok and not results["host_foreground_changed"] \
                and not results["host_trae_window_added"]:
            results["verdict"] = "hidden_trae_feasible"
        elif results["host_foreground_changed"] or results["host_trae_window_added"]:
            results["verdict"] = "host_interference"
        else:
            results["verdict"] = "partial_or_failed"
    except Exception as exc:  # noqa: BLE001
        results.setdefault("error", repr(exc))
        results.setdefault("verdict", "error")
    finally:
        if worker is not None:
            worker.close()
        if launch and launch.get("ok"):
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(launch["pid"])],
                           capture_output=True, text=True)
            results["second_instance_killed"] = True
        if hdesk:
            results["closedesktop_ok"] = bool(user32.CloseDesktop(wintypes.HANDLE(int(hdesk))))
        shutil.rmtree(profile, ignore_errors=True)
    out = run_dir / "trae_hidden.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in
                      ("run_id", "verdict", "launch", "hidden_window_found", "cdp_reachable",
                       "cdp_read", "host_foreground_changed", "host_cursor_displacement",
                       "host_trae_window_added", "second_instance_killed", "closedesktop_ok",
                       "error")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Keep-alive hidden-desktop Trae second-instance session manager (E17 follow-up).

Launches ONE Trae on a hidden desktop with a PERSISTENT separate --user-data-dir (so a
login, once done by the user, survives across runs) and a fixed --remote-debugging-port.
Later runs ATTACH by desktop name (OpenDesktopW) instead of relaunching. Only an explicit
`stop` kills the instance. Host zero-interference: never SwitchDesktop; the host Trae
profile/single-instance lock is never touched (distinct profile + port).

Login is USER-driven (QR scan / credentials on the second account): this manager never
inputs credentials and never sends chat. `inspect` dumps the page DOM read-only over CDP so
we can see whether it is at first-run setup, login, or a logged-in chat root.

State -> var/experiments/hidden_trae_session.json (gitignored). Profile ->
var/experiments/hidden_trae_profile (gitignored; holds the second-account session locally).

CLI: python src/probe/hidden_trae_session.py {launch|status|stop|inspect} [--port 9333]
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
PROBE_DIR = Path(__file__).parent
for _p in (str(ROOT), str(PROBE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_trae_hidden as et  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402
import win32_helpers as wh  # noqa: E402

user32 = e8.user32
GENERIC_ALL = e8.GENERIC_ALL
DESKTOP_NAME = "GBTraeKeepAlive"
STATE_PATH = ROOT / "var" / "experiments" / "hidden_trae_session.json"
PROFILE_DIR = ROOT / "var" / "experiments" / "hidden_trae_profile"
DEFAULT_PROJECT = r"D:\QoderTest\guibridge-demo-workspace"
DOM_SCRIPT = PROBE_DIR / "cdp_dom_dump.mjs"

user32.OpenDesktopW.restype = wintypes.HANDLE
user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]


def load_state() -> dict | None:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_state() -> None:
    STATE_PATH.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    return int(pid) in e13._process_tree()


def _open_worker(desktop: str) -> tuple[int, e8.DesktopWorker]:
    hdesk = user32.OpenDesktopW(desktop, 0, False, GENERIC_ALL)
    if not hdesk:
        raise ctypes.WinError(ctypes.get_last_error())
    worker = e8.DesktopWorker(int(hdesk))
    if not worker.desktop_ok:
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
        raise RuntimeError(f"attach worker desktop setup failed: {worker.start_error}")
    return int(hdesk), worker


def _resolve_main(worker, pid: int) -> dict | None:
    tree = et._descendants(pid)

    def _enum():
        out = []
        for w in wh.enum_top_level_windows():
            if w["visible"] and w["pid"] in tree and w["class"] == "Chrome_WidgetWin_1":
                r = wh.window_rect(w["hwnd"])
                if r[2] > 200 and r[3] > 200:
                    out.append({"hwnd": w["hwnd"], "rect": list(r), "title_len": len(w["title"])})
        return out
    cand = worker.run(_enum)
    if not cand:
        return None
    return max(cand, key=lambda w: w["rect"][2] * w["rect"][3])


def _cdp_dump(port: int) -> dict:
    node = shutil.which("node")
    if not node:
        return {"ok": False, "error": "node not found"}
    pr = subprocess.run([node, str(DOM_SCRIPT), str(port)], capture_output=True, text=True,
                        encoding="utf-8", timeout=25)
    try:
        return json.loads(pr.stdout.strip())
    except json.JSONDecodeError:
        return {"ok": False, "raw": pr.stdout.strip()[:300], "err": pr.stderr.strip()[:200]}


def ensure_session(port: int = 9333, timeout: float = 60.0,
                   project: str | None = DEFAULT_PROJECT) -> tuple[int, e8.DesktopWorker, dict]:
    """Return (hdesk, worker, state) with an OPEN worker. Caller closes worker + CloseDesktop
    but MUST NOT kill the instance (keep-alive). Reuses an alive instance; else launches one
    with the persistent profile and waits for CDP + main window."""
    st = load_state()
    if st and _alive(st["pid"]):
        hdesk, worker = _open_worker(st["desktop"])
        main = _resolve_main(worker, st["pid"])
        if main:
            st["hwnd"] = main["hwnd"]
            save_state(st)
        return hdesk, worker, {**st, "reused": True, "main_window": main}

    desktop = DESKTOP_NAME
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    if not hdesk:
        raise ctypes.WinError(ctypes.get_last_error())
    worker = e8.DesktopWorker(int(hdesk))
    launch: dict = {}
    try:
        if not worker.desktop_ok:
            raise RuntimeError(f"worker desktop setup failed: {worker.start_error}")
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        proj = project if project and Path(project).exists() else None
        launch = et._launch_trae(desktop, str(PROFILE_DIR), port, proj)
        if not launch.get("ok"):
            raise RuntimeError(f"launch failed: {launch}")
        pid = launch["pid"]
        main = None
        cdp = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            main = _resolve_main(worker, pid)
            cdp = bool(_cdp_dump(port).get("ok"))
            if main and cdp:
                break
            time.sleep(1.0)
        state = {"desktop": desktop, "pid": pid, "port": port, "profile": str(PROFILE_DIR),
                 "project": proj, "hwnd": main["hwnd"] if main else None,
                 "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "cdp_reachable": cdp}
        save_state(state)
        return int(hdesk), worker, {**state, "reused": False, "main_window": main}
    except Exception:
        if launch.get("ok"):
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(launch["pid"])],
                           capture_output=True, text=True)
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
        clear_state()
        raise


def status_session() -> dict:
    st = load_state()
    if not st:
        return {"session": False}
    return {"session": True, "desktop": st["desktop"], "pid": st["pid"], "port": st["port"],
            "alive": _alive(st["pid"]), "hwnd": st.get("hwnd"), "profile": st.get("profile"),
            "created_at": st.get("created_at")}


def stop_session(purge: bool = False) -> dict:
    st = load_state()
    out: dict = {"had_session": bool(st)}
    if st:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(st["pid"])], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
        out["killed_pid"] = st["pid"]
        hdesk = user32.OpenDesktopW(st["desktop"], 0, False, GENERIC_ALL)
        if hdesk:
            out["closedesktop_ok"] = bool(user32.CloseDesktop(wintypes.HANDLE(int(hdesk))))
        clear_state()
    if purge:
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        out["profile_purged"] = True
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["launch", "status", "stop", "inspect"])
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--purge", action="store_true")
    args = ap.parse_args()
    if args.cmd == "status":
        print(json.dumps(status_session(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop_session(args.purge), ensure_ascii=False, indent=2))
        return 0
    hdesk, worker, state = ensure_session(args.port, args.timeout)
    try:
        if args.cmd == "inspect":
            dump = _cdp_dump(state["port"])
            fg0 = int(user32.GetForegroundWindow() or 0)
            print(json.dumps({"session": {k: state.get(k) for k in
                                          ("desktop", "pid", "port", "reused", "hwnd", "cdp_reachable")},
                              "host_fg": fg0, "dom": dump}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({**state, "worker_desktop_ok": worker.desktop_ok},
                             ensure_ascii=False, indent=2))
    finally:
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(hdesk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
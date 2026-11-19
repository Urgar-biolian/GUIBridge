"""Keep-alive hidden-desktop WeChat session manager (E15 follow-up).

Problem this fixes: every probe run used to `taskkill /F` the hidden WeChat stub in its
finally block, so the second-account session dropped right after each phone login confirm
and the next run needed a fresh confirm (user was forced to log in 4+ times).

New model: login ONCE, KEEP the stub alive across runs, ATTACH repeatedly to the same
logged-in window for measurement, and only kill on an explicit `stop`. The stub lives on a
hidden desktop (CreateProcessW lpDesktop); it keeps the desktop object alive after the
launching process exits, so a later run re-opens it by name with OpenDesktopW. Host
zero-interference: never SwitchDesktop, host foreground/cursor untouched.

State -> var/experiments/hidden_wechat_session.json (gitignored). No private chat/contact
text or account nickname is persisted (only desktop name, stub pid, chat hwnd, timestamp).

CLI: python src/probe/hidden_session.py {launch|status|stop}
  launch  ensure a logged-in session exists (reuse if alive), keep it alive, report
  status  report whether a session exists and the stub is alive (read-only)
  stop    kill ONLY the stub tree + close desktop + clear state (explicit cleanup)
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
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
import experiment_real_app_hidden as e9  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402

user32 = e8.user32
GENERIC_ALL = e8.GENERIC_ALL
DESKTOP_NAME = "GBWeChatKeepAlive"
STATE_PATH = ROOT / "var" / "experiments" / "hidden_wechat_session.json"
CHAT_MIN_W = 600  # logged-in chat main is >=600 wide; login/enter page is smaller

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


def _stub_alive(pid: int) -> bool:
    return int(pid) in e13._process_tree()


def _resolve_chat(worker) -> int | None:
    mains = e13._qt_mains(worker)
    big = [m for m in mains if m["rect"][2] >= CHAT_MIN_W]
    return max(big, key=lambda m: m["area"])["hwnd"] if big else None


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


def _login_loop(worker, timeout: float = 180.0) -> tuple[bool, int | None, bool]:
    """Auto-enter the saved SECOND account (never the host nick). Returns (logged_in, chat_hwnd, auto)."""
    logged_in, ch, auto = False, None, False
    deadline = time.time() + timeout
    while time.time() < deadline and not logged_in:
        mains = e13._qt_mains(worker)
        if mains:
            biggest = max(mains, key=lambda m: m["area"])
            if biggest["rect"][2] < CHAT_MIN_W:
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
            else:
                logged_in, ch = True, biggest["hwnd"]
        time.sleep(0.5)
    return logged_in, ch, auto


def ensure_session(timeout: float = 180.0) -> tuple[int, e8.DesktopWorker, int, dict]:
    """Return (hdesk, worker, chat_hwnd, state) with an OPEN worker for the caller to use.

    Reuses an alive logged-in session (attach, no phone confirm). If the stub is alive but
    logged out, re-logins the SAME instance. Otherwise launches a fresh hidden instance and
    logs in once. Caller MUST close worker + CloseDesktop(hdesk) when done, but MUST NOT kill
    the stub — that is what keeps the session alive for the next run. On login failure the
    fresh stub is cleaned up so no half-logged-in instance is left behind.
    """
    st = load_state()
    if st and _stub_alive(st["stub_pid"]):
        hdesk, worker = _open_worker(st["desktop"])
        ch = _resolve_chat(worker)
        if ch:
            if ch != st.get("chat_hwnd"):
                st["chat_hwnd"] = ch
                save_state(st)
            return hdesk, worker, ch, {**st, "reused": True}
        logged_in, ch, _ = _login_loop(worker, timeout)
        if logged_in:
            st["chat_hwnd"] = ch
            save_state(st)
            return hdesk, worker, ch, {**st, "reused": True, "relogin": True}
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(hdesk))
        raise RuntimeError("session stub alive but re-login failed (logged out?)")

    desktop = DESKTOP_NAME
    hdesk = user32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None)
    if not hdesk:
        raise ctypes.WinError(ctypes.get_last_error())
    worker = e8.DesktopWorker(int(hdesk))
    launch: dict = {}
    try:
        if not worker.desktop_ok:
            raise RuntimeError(f"worker desktop setup failed: {worker.start_error}")
        launch = e9._launch_real(e13.WECHAT_EXE, desktop)
        if not launch.get("ok"):
            raise RuntimeError(f"launch failed: {launch}")
        logged_in, ch, _ = _login_loop(worker, timeout)
        if not logged_in:
            raise RuntimeError("login_timeout")
        state = {"desktop": desktop, "stub_pid": launch["pid"], "chat_hwnd": ch,
                 "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "logged_in": True}
        save_state(state)
        return int(hdesk), worker, ch, {**state, "reused": False}
    except Exception:
        if launch.get("ok"):
            e13._cleanup_stub(launch["pid"])
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
        clear_state()
        raise


def status_session() -> dict:
    st = load_state()
    if not st:
        return {"session": False}
    return {"session": True, "desktop": st["desktop"], "stub_pid": st["stub_pid"],
            "stub_alive": _stub_alive(st["stub_pid"]), "chat_hwnd": st.get("chat_hwnd"),
            "created_at": st.get("created_at")}


def stop_session() -> dict:
    """Explicit cleanup: kill ONLY the stub tree, close desktop, clear state."""
    st = load_state()
    out: dict = {"had_session": bool(st)}
    if st:
        out["cleanup_stub"] = e13._cleanup_stub(st["stub_pid"])
        hdesk = user32.OpenDesktopW(st["desktop"], 0, False, GENERIC_ALL)
        if hdesk:
            out["closedesktop_ok"] = bool(user32.CloseDesktop(wintypes.HANDLE(int(hdesk))))
        clear_state()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["launch", "status", "stop"])
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()
    if args.cmd == "status":
        print(json.dumps(status_session(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop_session(), ensure_ascii=False, indent=2))
        return 0
    hdesk, worker, ch, state = ensure_session(args.timeout)
    try:
        print(json.dumps({**state, "chat_hwnd": int(ch), "worker_desktop_ok": worker.desktop_ok},
                         ensure_ascii=False, indent=2))
    finally:
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(hdesk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
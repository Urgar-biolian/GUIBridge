"""Keep-alive hidden-desktop session REGISTRY (facade over the per-app managers).

Multiple hidden-desktop sessions (WeChat, Trae, ...) coexist, each independently kept
alive by its own manager. This module is a thin index/registry: it discovers the per-app
state files, normalizes them into one record shape, and delegates launch/attach/stop to
the EXISTING managers (hidden_session.py / hidden_trae_session.py) so their app-specific
login/CDP logic and verified zero-interference chains are untouched. It is NOT a serial
FIFO task queue — sessions run concurrently.

`export` writes a normalized array to var/experiments/hidden_sessions.json (gitignored)
for the Rust mirror's session-picker panel to read.

CLI: python src/probe/hidden_sessions.py {list|status|attach|stop|export} [--name N] [--purge] [--port P]
"""

from __future__ import annotations

import argparse
import json
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = Path(__file__).parent
for _p in (str(ROOT), str(PROBE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_wechat_hidden_login as e13  # noqa: E402
import hidden_session as hs  # noqa: E402
import hidden_trae_session as ht  # noqa: E402

user32 = e8.user32
REGISTRY_PATH = ROOT / "var" / "experiments" / "hidden_sessions.json"

# name -> (kind, manager module). The manager owns launch/attach/stop specifics.
SOURCES = {
    "wechat": ("wechat", hs),
    "trae": ("trae", ht),
}


def _alive(pid: int | None) -> bool:
    return bool(pid) and int(pid) in e13._process_tree()


def _normalize(st: dict, kind: str, name: str) -> dict:
    pid = st.get("stub_pid") if kind == "wechat" else st.get("pid")
    hwnd = st.get("chat_hwnd") if kind == "wechat" else st.get("hwnd")
    return {
        "name": name,
        "kind": kind,
        "desktop": st.get("desktop"),
        "pid": pid,
        "alive": _alive(pid),
        "hwnd": hwnd,
        "port": st.get("port"),
        "profile": st.get("profile"),
        "created_at": st.get("created_at"),
    }


def list_sessions() -> list[dict]:
    out = []
    for name, (kind, mod) in SOURCES.items():
        st = mod.load_state()
        if st:
            out.append(_normalize(st, kind, name))
    return out


def get_session(name: str) -> dict | None:
    if name not in SOURCES:
        return None
    kind, mod = SOURCES[name]
    st = mod.load_state()
    return _normalize(st, kind, name) if st else None


def export_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    sessions = list_sessions()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    return sessions


def attach(name: str, port: int = 9333):
    """Delegate to the app manager; return (hdesk, worker, record) with an OPEN worker.

    Caller MUST close worker + CloseDesktop(hdesk) but MUST NOT kill the stub (keep-alive).
    """
    if name not in SOURCES:
        raise KeyError(f"unknown session {name!r}; known: {list(SOURCES)}")
    kind, mod = SOURCES[name]
    if kind == "wechat":
        hdesk, worker, _ch, state = mod.ensure_session()
    else:
        hdesk, worker, state = mod.ensure_session(port=port)
    return int(hdesk), worker, _normalize(state, kind, name)


def stop(name: str, purge: bool = False) -> dict:
    if name not in SOURCES:
        raise KeyError(f"unknown session {name!r}; known: {list(SOURCES)}")
    kind, mod = SOURCES[name]
    if kind == "wechat":
        return mod.stop_session()
    return mod.stop_session(purge=purge)


def main() -> int:
    ap = argparse.ArgumentParser(description="Keep-alive hidden-desktop session registry")
    ap.add_argument("cmd", choices=["list", "status", "attach", "stop", "export"])
    ap.add_argument("--name", default=None, help="session name (wechat|trae)")
    ap.add_argument("--port", type=int, default=9333, help="Trae CDP port for attach")
    ap.add_argument("--purge", action="store_true", help="Trae stop: also delete cloned profile")
    args = ap.parse_args()

    if args.cmd == "list":
        print(json.dumps(list_sessions(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "export":
        sessions = export_registry()
        print(f"WROTE {REGISTRY_PATH} ({len(sessions)} sessions)")
        print(json.dumps(sessions, ensure_ascii=False, indent=2))
        return 0
    if not args.name:
        print("ABORT: --name is required for status/attach/stop")
        return 2
    if args.cmd == "status":
        print(json.dumps(get_session(args.name) or {"session": False}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop(args.name, args.purge), ensure_ascii=False, indent=2))
        return 0
    hdesk, worker, record = attach(args.name, args.port)
    try:
        print(json.dumps({**record, "worker_desktop_ok": worker.desktop_ok},
                         ensure_ascii=False, indent=2))
    finally:
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(hdesk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
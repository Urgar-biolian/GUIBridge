"""Clone the HOST Trae login state into the hidden instance's profile (authorized reuse).

Read-only on the host profile (host Trae keeps running — reading does not log it out);
writes only into the hidden profile. Trae stores auth via Electron safeStorage/DPAPI
(per-Windows-user, key in 'Local State') + web storage, so copying the auth-relevant
subset may let the hidden instance (same user) decrypt and reuse the session.

Steps: stop hidden instance -> copy auth subset host->hidden -> relaunch hidden -> report
whether the workbench shows a logged-in user (user_is_login / no 登录 welcome).

Machine-binding may still block reuse; this is an experiment, not a guarantee. Host files
are never modified. Skips locked leveldb LOCK files. Raw result -> var/experiments (gitignored).
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = Path(__file__).parent
for _p in (str(ROOT), str(PROBE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hidden_trae_session as hs  # noqa: E402

HOST_PROFILE = Path(os.environ["APPDATA"]) / "Trae"
HIDDEN_PROFILE = hs.PROFILE_DIR
RUNS = ROOT / "var" / "experiments"

AUTH_FILES = ["machineid", "Local State", "Preferences"]
AUTH_DIRS = ["aha", "ahanet", "Local Storage", "Session Storage", "Network"]
GS_FILES = ["state.vscdb", "state.vscdb.backup", "storage.json",
            "state.vscdb-wal", "state.vscdb-shm"]


def _copy_file(src: Path, dst: Path) -> dict:
    if not src.exists():
        return {"path": str(src.relative_to(HOST_PROFILE)), "skipped": "absent"}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return {"path": str(src.relative_to(HOST_PROFILE)), "copied": dst.stat().st_size}
    except Exception as exc:  # noqa: BLE001
        return {"path": str(src.relative_to(HOST_PROFILE)), "error": repr(exc)}


def _copy_dir(name: str) -> dict:
    src = HOST_PROFILE / name
    dst = HIDDEN_PROFILE / name
    if not src.exists():
        return {"dir": name, "skipped": "absent"}
    copied, errors = 0, []
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        if f.name in ("LOCK",):
            continue
        rel = f.relative_to(src)
        try:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc!r}")
    return {"dir": name, "files_copied": copied, "errors": errors[:5]}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"run_id": run_id, "host_profile": str(HOST_PROFILE),
                     "hidden_profile": str(HIDDEN_PROFILE)}
    results["stop_hidden"] = hs.stop_session(purge=False)
    HIDDEN_PROFILE.mkdir(parents=True, exist_ok=True)
    copies = []
    for name in AUTH_FILES:
        copies.append(_copy_file(HOST_PROFILE / name, HIDDEN_PROFILE / name))
    for name in AUTH_DIRS:
        copies.append(_copy_dir(name))
    gs = HOST_PROFILE / "User" / "globalStorage"
    for name in GS_FILES:
        copies.append(_copy_file(gs / name, HIDDEN_PROFILE / "User" / "globalStorage" / name))
    results["copies"] = copies
    try:
        hdesk, worker, st = hs.ensure_session(9333, 70)
        import win32_helpers as wh  # noqa: E402
        import experiment_hidden_desktop as e8  # noqa: E402
        from ctypes import wintypes  # noqa: E402
        try:
            results["relaunch"] = {k: st.get(k) for k in ("pid", "reused", "hwnd", "cdp_reachable")}
            time.sleep(6)
            dump = hs._cdp_dump(9333)
            results["dom"] = dump
            results["host_fg"] = int(e8.user32.GetForegroundWindow() or 0)
        finally:
            worker.close()
            e8.user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
    except Exception as exc:  # noqa: BLE001
        results["relaunch_error"] = repr(exc)
    out = run_dir / "trae_session_clone.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    dom = results.get("dom") or {}
    page = (dom.get("pages") or [{}])[0]
    val = page.get("value")
    print(json.dumps({"run_id": run_id, "relaunch": results.get("relaunch"),
                      "relaunch_error": results.get("relaunch_error"),
                      "host_fg": results.get("host_fg"),
                      "page_value": (val[:800] if isinstance(val, str) else val)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
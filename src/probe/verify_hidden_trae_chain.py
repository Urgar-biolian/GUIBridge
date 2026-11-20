"""E17e: full chain on the HIDDEN logged-in Trae — send a chat task, read the reply.

Prereq: hidden_trae_session keep-alive logged-in instance on port 9333 (full-profile clone,
§27.3). Drives the FORMAL TraeAdapter(port=9333) send_task(chat) -> get_status -> read_result
against the isolated demo workspace, and measures HOST foreground/cursor before/after to
confirm zero interference (the hidden instance must not touch the host).

GATED: --authorize-live-write required (fresh chat-send authorization). Chat mode only;
fixed harmless message asks Trae to reply "OK" and do nothing else (chat cannot edit files).
--project-path must be a git repo whose basename matches the HIDDEN Trae window title; the
probe verifies zero workspace change after the send. Raw JSON -> var/experiments (gitignored).
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import hidden_trae_session as hs  # noqa: E402
import win32_helpers as wh  # noqa: E402
import experiment_hidden_desktop as e8  # noqa: E402
from adapters.trae.adapter import AdapterError, TraeAdapter  # noqa: E402
from events.store import EventStore  # noqa: E402

RUNS = ROOT / "var" / "experiments"
PORT = 9333
FIXED_MESSAGE = "请只回复 OK 两个字母，不要执行任何其他操作。"
user32 = e8.user32


def _git_changed_files(project_path: str) -> list[str]:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=project_path,
                          capture_output=True, text=True)
    return [line[3:] for line in proc.stdout.splitlines() if line.strip()]


def _is_git_repo(project_path: str) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_path,
                          capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize-live-write", action="store_true")
    ap.add_argument("--project-path", default=r"D:\QoderTest\guibridge-demo-workspace")
    ap.add_argument("--reply-timeout", type=float, default=90.0)
    args = ap.parse_args()
    if not args.authorize_live_write:
        print("REFUSED: --authorize-live-write required (fresh chat-send authorization).")
        return 3
    project_path = str(Path(args.project_path).resolve())
    if not _is_git_repo(project_path):
        print("ABORT: --project-path must be a git repo (meaningful zero-change check)")
        return 2
    before_files = _git_changed_files(project_path)

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"run_id": run_id, "cdp_port": PORT, "project_path": project_path,
                     "mode": "chat", "fixed_message": FIXED_MESSAGE}
    hdesk, worker, st = hs.ensure_session(PORT, 60)
    store = EventStore(":memory:")
    try:
        hwnd = st.get("hwnd")
        title = worker.run(lambda: wh.window_title(hwnd)) if hwnd else ""
        results["hidden_hwnd"] = hwnd
        results["hidden_title"] = title
        if Path(project_path).name not in title:
            print(f"ABORT: hidden Trae workspace mismatch ({title!r})")
            return 2
        fg0 = int(user32.GetForegroundWindow() or 0)
        cur0 = wh.cursor_pos()
        results["host_fg_before"] = fg0
        adapter = TraeAdapter(port=PORT, store=store)
        results["probe_channels"] = adapter.probe_channels()
        if not results["probe_channels"].get("cdp"):
            print(f"ABORT: adapter CDP not reachable on {PORT}")
            return 2
        record = adapter.send_task(project_path, FIXED_MESSAGE, mode="chat")
        task_id = record.task_id
        results["task_id"] = task_id
        results["submitted_state"] = record.state
        deadline = time.time() + args.reply_timeout
        status = adapter.get_status(task_id)
        while status.state not in ("claimed_done", "verified", "failed", "awaiting_approval") \
                and time.time() < deadline:
            time.sleep(1.0)
            status = adapter.get_status(task_id)
        result = adapter.read_result(task_id)
        after_files = _git_changed_files(project_path)
        fg1 = int(user32.GetForegroundWindow() or 0)
        cx, cy = wh.cursor_pos()
        results["task_state"] = status.state
        results["reply_text"] = result.get("reply_text")
        results["reply_untrusted"] = True
        results["reply_ok"] = "OK" in (result.get("reply_text") or "")
        results["workspace_unchanged"] = after_files == before_files
        results["changed_files_before"] = before_files
        results["changed_files_after"] = after_files
        results["host_fg_after"] = fg1
        results["host_foreground_changed"] = fg1 != fg0
        results["host_cursor_displacement"] = abs(cx - cur0[0]) + abs(cy - cur0[1])
        ok = results["reply_ok"] and results["workspace_unchanged"] \
            and not results["host_foreground_changed"] and results["host_cursor_displacement"] == 0
        results["verdict"] = "hidden_chain_verified" if ok else "partial_or_failed"
    except AdapterError as exc:
        results["adapter_error"] = f"{exc.code}: {exc}"
        results["verdict"] = "adapter_error"
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results.setdefault("verdict", "error")
    finally:
        store.close()
        worker.close()
        user32.CloseDesktop(wintypes.HANDLE(int(hdesk)))
    out = out_dir / "hidden_trae_chain.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in
                      ("run_id", "verdict", "hidden_title", "probe_channels", "task_state",
                       "reply_ok", "reply_text", "workspace_unchanged", "host_foreground_changed",
                       "host_cursor_displacement", "adapter_error", "error")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""R5 measurement instrument: FocusGuard measurement of Trae send_task's send click.

GATED — defaults to refusing any live write. The send_task send-click risk is
currently `unknown` in the capability table; measuring it requires FRESH explicit
user live-write authorization (design R5). A prior "全部授权" does NOT auto-extend
to re-sending. Without --authorize-live-write this probe connects to nothing,
sends nothing, and exits 3.

Run with --authorize-live-write ONLY after the user has explicitly authorized a
one-off harmless Chat send. Chat mode only; agent mode is never exercised (it may
auto-edit files / run long tasks). The fixed message asks Trae to reply "OK" and
do nothing else. --project-path must point to an ISOLATED demo workspace, never a
real user project; the probe verifies zero workspace change after the send.
Writes var/experiments/<run_id>/trae_send_focus.json (gitignored).

Status: instrument dev-complete; the live measurement itself is PENDING R5
authorization and has not been run. The refusal gate is the only path verified
without authorization.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import run_experiments as rx  # noqa: E402
from trae_cdp_focus import find_trae_hwnd  # noqa: E402
from adapters.trae.adapter import AdapterError, TraeAdapter  # noqa: E402
from events.store import EventStore  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

PORT = 9222
FIXED_MESSAGE = "请只回复 OK 两个字母，不要执行任何其他操作。"


def _git_changed_files(project_path: str) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=project_path, capture_output=True, text=True
    )
    return [line[3:] for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Gated R5 send_task focus measurement")
    parser.add_argument(
        "--authorize-live-write", action="store_true",
        help="explicit fresh user authorization for a one-off harmless Chat send (R5)",
    )
    parser.add_argument(
        "--project-path", default=None,
        help="isolated demo workspace for the live send (never a real user project)",
    )
    args = parser.parse_args()

    if not args.authorize_live_write:
        print("REFUSED: R5 live-write authorization required.")
        print("The send_task send-click risk is unknown; measuring it needs fresh explicit")
        print("user authorization. No message was sent and no CDP connection was made.")
        print("Re-run with --authorize-live-write --project-path <isolated-demo> ONLY after")
        print("the user has explicitly authorized a one-off harmless Chat send.")
        return 3

    if not args.project_path:
        print("ABORT: --project-path (isolated demo workspace) is required for a live send")
        return 2
    project_path = str(Path(args.project_path).resolve())
    before_files = _git_changed_files(project_path)

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    trae_hwnd = find_trae_hwnd()
    if trae_hwnd is None:
        print("ABORT: Trae top-level window not found")
        return 2
    guard = Win32FocusGuard(trae_hwnd)
    store = EventStore(":memory:")
    adapter = TraeAdapter(port=PORT, store=store)
    print(f"trae_hwnd={trae_hwnd} title={wh.window_title(trae_hwnd)!r} project={project_path}")

    wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)

    def send():
        return adapter.send_task(project_path, FIXED_MESSAGE, mode="chat")

    try:
        run = guard.wrap_with_events(send)
    except AdapterError as exc:
        print(f"ABORT: send_task failed before/at submit: {exc.code}: {exc}")
        store.close()
        return 2
    record = run.result
    task_id = record.task_id

    status = adapter.get_status(task_id)
    result = adapter.read_result(task_id)
    after_files = _git_changed_files(project_path)
    workspace_unchanged = after_files == before_files
    reply_ok = "OK" in (result.get("reply_text") or "")

    payload = {
        "run_id": run_id,
        "env": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
            ).stdout.strip(),
        },
        "trae_hwnd": trae_hwnd,
        "cdp_port": PORT,
        "project_path": project_path,
        "mode": "chat",
        "fixed_message": FIXED_MESSAGE,
        "task_id": task_id,
        "send_focus": {
            "cursor_displacement": run.cursor_displacement,
            "unexpected_focus_switch": run.unexpected_focus_switch,
            "external_input_during_window": run.external_input_during_window,
            "event_hook_active": run.event_hook_active,
            "poll_events": [fg for _, fg in run.foreground_events],
            "hook_events": [fg for _, fg in run.hook_foreground_events],
        },
        "task_state": status.state,
        "reply_text": result.get("reply_text"),
        "reply_untrusted": True,
        "reply_ok": reply_ok,
        "workspace_unchanged": workspace_unchanged,
        "changed_files_before": before_files,
        "changed_files_after": after_files,
    }
    (out_dir / "trae_send_focus.json").write_text(
        json.dumps(rx.jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    store.close()
    sf = payload["send_focus"]
    print(f"WROTE {out_dir / 'trae_send_focus.json'}")
    print(
        f"cursor={sf['cursor_displacement']} focus_switch={sf['unexpected_focus_switch']} "
        f"ext={sf['external_input_during_window']} state={status.state} "
        f"reply_ok={reply_ok} workspace_unchanged={workspace_unchanged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
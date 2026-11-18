"""REAL Trae agent live demo — ONLY on the isolated demo workspace.

Safety gates (refuse rather than risk the real project):
  * --authorize-live-agent required (else exit 3); agent mode auto-edits files.
  * --project-path must be a git repo whose basename matches the selected Trae page;
    basename 'Agui' (the real project) is hard-blocked.
  * The CDP page is selected by the demo workspace title; NO fallback to the first
    Trae page (which could be the real project). Missing demo page -> exit 2.
  * Manual approval must be pre-set by a human in that Trae window; this build cannot
    force it via CDP. If approval is not manual/absent -> exit 4 (principle 7 human loop).
  * Task scope is index.html only; an independent Verifier checks git diff scope + tests.
    Reply text is untrusted data and is NEVER executed.

Evidence (store db) goes to gitignored var/. Nothing here touches the frozen adapter
default path: DemoAdapter only overrides target selection for this isolated run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from adapters.trae.adapter import AdapterError, TraeAdapter  # noqa: E402
from events.store import EventStore  # noqa: E402
from execution.verifier import Verifier  # noqa: E402
from perception.cdp import list_targets  # noqa: E402

PORT = 9222
DEMO_TASK = ("为密码输入框新增显示/隐藏切换按钮：仅修改 index.html，"
             "保持 tests/password.test.mjs 现有测试通过，不要改动其它文件。")
REAL_PROJECT_BLOCKLIST = ("agui",)


def _is_git_repo(path: Path) -> bool:
    try:
        subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False


class DemoAdapter(TraeAdapter):
    """Real adapter, but target selection locked to the demo workspace page."""

    def __init__(self, port: int, store, demo_basename: str):
        super().__init__(port, store)
        self._demo_basename = demo_basename.lower()

    async def _target(self):
        targets = list_targets(self.port)
        pages = [t for t in targets if t.type == "page"]
        match = [t for t in pages if self._demo_basename in t.title.lower()]
        if not match:
            raise AdapterError("locator_missing",
                               f"demo page '{self._demo_basename}' not on port {self.port}; refusing fallback")
        if any(b in match[0].title.lower() for b in REAL_PROJECT_BLOCKLIST):
            raise AdapterError("conflict", "refusing: selected page looks like the real project")
        return match[0]


def _select_demo_title(basename: str) -> str:
    pages = [t for t in list_targets(PORT) if t.type == "page"]
    match = [t for t in pages if basename.lower() in t.title.lower()]
    if not match:
        raise SystemExit(2)
    if any(b in match[0].title.lower() for b in REAL_PROJECT_BLOCKLIST):
        raise SystemExit(2)
    return match[0].title


def run(project_path: Path, poll_seconds: float = 120.0) -> dict:
    basename = project_path.name
    if basename.lower() in REAL_PROJECT_BLOCKLIST:
        raise AdapterError("conflict", "refusing: project_path is the real project")
    if not _is_git_repo(project_path):
        raise SystemExit(2)
    title = _select_demo_title(basename)

    var = ROOT / "var" / "agent-live"
    var.mkdir(parents=True, exist_ok=True)
    store = EventStore(str(var / "agent-live.db"))
    adapter = DemoAdapter(PORT, store, basename)

    approval = adapter.force_manual_approval()
    if approval not in ("manual", "absent"):
        store.close()
        raise SystemExit(4)

    record = adapter.send_task(str(project_path), DEMO_TASK, mode="agent",
                               allow_files=["index.html"], approve_agent=True)
    task_id = record.task_id

    deadline = time.time() + poll_seconds
    status = adapter.get_status(task_id)
    while status.state not in ("claimed_done", "verified", "failed", "awaiting_approval") \
            and time.time() < deadline:
        time.sleep(1.0)
        status = adapter.get_status(task_id)
    result = adapter.read_result(task_id)

    verifier = Verifier(project_path, allowed_files=["index.html"],
                        test_command=["node", "--test", "tests/password.test.mjs"],
                        store=store, task_id=task_id)
    verified = verifier.verify(claimed_reply=result["reply_text"])
    summary = {
        "task_id": task_id, "selected_page": title, "mode": "agent",
        "approval_precondition": approval, "final_state": status.state,
        "reply_untrusted": result["untrusted"], "reply_executed": False,
        "claimed_done": result["claimed_done"], "verified": verified,
    }
    store.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize-live-agent", action="store_true")
    ap.add_argument("--project-path", required=True)
    ap.add_argument("--poll-seconds", type=float, default=120.0)
    args = ap.parse_args()
    if not args.authorize_live_agent:
        print("refusing: agent live requires --authorize-live-agent (isolated demo only)", file=sys.stderr)
        return 3
    summary = run(Path(args.project_path), args.poll_seconds)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["verified"]["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
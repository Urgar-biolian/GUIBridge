"""Planning-side handoff for S3: task package → send → poll → read → independent verify → report.

Run it against the pre-G1 simulation to see the whole chain, including the `verified` step the
executor can never grant itself:

    python examples/handoff_demo.py --node node

`client` is anything with `send_task` / `get_status` / `read_result` — the MCP tool surface has the
same names, so a live run passes an MCP client instead of the in-process plane.

Two rules from docs/agent.md are structural here, not advisory: the reply text is only ever copied
into the report (never executed, never parsed for instructions), and `verified` comes from Git plus
the acceptance commands the planner chose, not from anything Trae said.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "packages", ROOT / "apps" / "desktop-agent"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from execution.verifier import Verifier  # noqa: E402

DEMO_APP = ROOT / "examples" / "demo-app"
TASK_TEXT = ("为 index.html 的密码输入框新增显示/隐藏切换按钮，按钮文本随状态在「显示」「隐藏」之间切换，"
             "并在 tests/ 里补一条覆盖该切换逻辑的测试。不要改动其他文件。")
PLAN_NOTE = "规划侧只提交任务包与验收条件；回复文本一律按 untrusted 数据处理，不作为指令执行。"
DONE_STATES = ("claimed_done", "verified")


class HandoffError(Exception):
    pass


def _awaiting_human(detail: str) -> HandoffError:
    return HandoffError(f"{detail} awaits a human approval; grant it in the Dashboard or POST /approvals, "
                        "then re-send the same package — the executor must not act meanwhile")


@dataclass
class TaskPackage:
    """交接协议第 1 步：规划侧产出的任务包（docs/agent.md）。"""

    project_path: str
    task: str = TASK_TEXT
    mode: str = "chat"
    allow_files: list[str] = field(default_factory=lambda: ["index.html", "tests/"])
    test_commands: list = field(default_factory=list)
    stop_condition: str = ("状态 unknown 或 failed 时停止并上报失败类型；两次尝试仍失败就改用更小的任务"
                          "（例如单文件注释修改），任何时候都不得伪造 verified")

    def as_dict(self) -> dict:
        return asdict(self)


def git(repo: Path | str, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise HandoffError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


# Passed per command instead of written into the workspace's config: a demo must not touch anyone's
# git identity, not even a throwaway repo's.
_SEED_IDENTITY = ("-c", "user.name=GUIBridge Demo", "-c", "user.email=demo@guibridge.local")


_TOGGLE_BUTTON = re.compile(r'[ \t]*<button\b[^>]*data-testid="toggle-password"[^>]*>.*?</button>\n?', re.S)
_TASK_COMMENT = re.compile(r'[ \t]*<!-- S3 演示任务：.*?-->\n?', re.S)


def _seed_before_state(index: Path) -> None:
    """Seed the copied demo app in its "before" state: reference implementation removed, tests kept.

    The reference stays in examples/demo-app/index.html as the single source of truth; a simulated
    run restores it through the writing stand-in, a live run lets Trae build it. Keeping the tests
    is what stops `node --test` from vacuously passing.
    """
    html = index.read_text(encoding="utf-8")
    html = _TOGGLE_BUTTON.sub("", html)
    html = _TASK_COMMENT.sub(
        "      <!-- S3 演示任务：为密码输入框新增显示/隐藏切换按钮；验收用例在 tests/，改动前必须失败。 -->\n",
        html)
    index.write_text(html, encoding="utf-8")


def prepare_workspace(dest: str | Path | None = None, source: Path = DEMO_APP) -> Path:
    """Copy the demo app into an independent git repo, so no real project is ever a demo target.

    A fresh copy is seeded in the "before" state (toggle removed, acceptance tests kept).
    An existing repo is reused as-is (its HEAD is the verification baseline) unless it has a remote,
    which means it is somebody's real project and the run refuses it.
    """
    target = Path(dest or Path(tempfile.gettempdir()) / "guibridge-demo-workspace").resolve()
    if (target / ".git").exists():
        try:
            remotes = git(target, "remote")
        except HandoffError as exc:
            # Windows leaves `.git/objects` behind when a delete hits read-only pack files, which looks
            # like a repository to a directory check and is unusable to git.
            raise HandoffError(f"{target} has no usable repository: {exc}; pick another --workspace") from exc
        if remotes:
            raise HandoffError(f"{target} has a git remote; demos must run on an isolated repository")
        return target
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise HandoffError(f"{target} is not empty and is not a git repository")
    for item in source.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)
        else:
            shutil.copytree(item, target / item.name)
    _seed_before_state(target / "index.html")
    git(target, "init", "-b", "main")
    git(target, "add", "-A")
    git(target, *_SEED_IDENTITY, "commit", "-m", "seed: demo app before the handoff task")
    return target


def poll(client, task_id: str, timeout: float = 120.0, interval: float = 0.5) -> tuple[dict, list[str]]:
    """Follow the state until it settles. Fixed waits are a polling gap only (docs/framework.md)."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while True:
        status = client.get_status(task_id)
        seen.append(status["state"])
        if status["state"] in DONE_STATES:
            return status, seen
        if status["state"] in ("failed", "unknown"):
            raise HandoffError(f"task {task_id} stopped in {status['state']}: {status.get('signals')}")
        if status["state"] == "awaiting_approval":
            raise _awaiting_human(f"task {task_id}")
        if time.monotonic() >= deadline:
            raise HandoffError(f"task {task_id} still {status['state']} after {timeout}s: {seen}")
        time.sleep(interval)


def handoff(client, package: TaskPackage, store, verifier: Verifier | None = None,
            window_id: str | None = None, approval_token: str | None = None,
            poll_timeout: float = 120.0) -> dict:
    """One handoff, reported back to the planner as data.

    `store` is the plane's own SQLite file, because the last transition is only accepted with
    `actor="verifier"` (docs/sql.md); a planner without store access gets the report and cannot lift
    the state itself. `approval_token` only ever switches auto-approval off — with none, and the
    session still on auto, the task stops in `awaiting_approval` for a human to clear.
    """
    if store is None:
        raise HandoffError("handoff needs the event store: only it can write the verified transition")
    verifier = verifier or Verifier()
    since_rev = git(Path(package.project_path), "rev-parse", "HEAD")

    options = {"mode": package.mode, "allow_files": package.allow_files,
               "acceptance": {"test_commands": package.test_commands}}
    if approval_token:
        # Only the adapter-level surface takes a token; the frozen MCP tool has no such argument, so a
        # live run over `mcp.server` arrives here without one and waits for a human.
        options["approval_token"] = approval_token
    try:
        record = client.send_task(package.project_path, package.task, **options)
    except Exception as exc:
        if getattr(exc, "code", None) != "approval_required":
            raise
        # The adapter refuses to click the auto-approval toggle without a token and stops before
        # touching anything else; that arrives as an error, not as an `awaiting_approval` state,
        # because the DOM signature for Trae's own prompt is still unverified (未验证项 3).
        raise _awaiting_human(f"task submission ({exc})") from exc
    task_id = record["task_id"]

    status, states = poll(client, task_id, timeout=poll_timeout)
    result = client.read_result(task_id)
    verification = verifier.verify(package.project_path, package.allow_files, package.test_commands,
                                   since_rev=since_rev)
    report = {"task_id": task_id, "package": package.as_dict(), "states": states,
              "signals": status["signals"], "planner_note": PLAN_NOTE,
              "reply": {"text": result["reply_text"], "untrusted": result["untrusted"],
                        "claimed_done": result["claimed_done"], "truncated": result["truncated"],
                        "evidence": result["evidence"]},
              "verification": verification, "final_state": verification["status"]}

    if verification["verified"]:
        evidence_id = store.record("verify", verification, task_id=task_id, window_id=window_id)
        store.set_task_state(task_id, "verified", evidence_id, actor="verifier")
        report["evidence_id"] = evidence_id
        report["final_state"] = store.get_task(task_id)["state"]
    return report


def approve_forcing_manual(client, window_id: str | None = None) -> str:
    """Grant what `force_manual_approval` needs: one single-use token for the approval-mode dropdown.

    In a live run a person does this through the Dashboard or `POST /approvals`, because the MCP tool
    surface has no `approval_token` (docs/api.md) and the request is waiting in `pending_approvals()`.
    Handing the token to `handoff` is the adapter-level equivalent: the switch turns auto-approval
    *off*, which is the safe direction, and it is gated as one `select` because F10 measured that a
    click on the trigger only opens the popover. Without it the task stops in `awaiting_approval`.
    """
    return client.grant_approval({"window_id": window_id or client.window_id,
                                  "semantic_ids": ["trae.chat.approval_mode"], "actions": ["select"]})


class _SimulatedEditClient:
    """The simulated desktop plus the one thing a fixture cannot do: write the planned edit.

    The plane, locator preconditions, state machine and store are the real S2 code; restoring the
    reference implementation stands in for Trae's edit. This is simulated evidence only — it does
    not prove Trae modifies files (that is the live test's job, docs/dev-status.md).
    """

    def __init__(self, plane):
        self.plane = plane
        self.channel, self.store, self.window_id = plane.channel, plane.store, plane.window_id

    def send_task(self, project_path, task, **opts):
        self.channel.reply_plan = [["思考中", 2], ["已按任务包补上切换按钮，测试全部通过 ✅", 1]]
        record = self.plane.send_task(project_path, task, **opts)
        if record["state"] == "submitted":
            reference = (DEMO_APP / "index.html").read_text(encoding="utf-8")
            Path(project_path, "index.html").write_text(reference, encoding="utf-8")
        return record

    def get_status(self, task_id):
        return self.plane.get_status(task_id)

    def read_result(self, task_id):
        return self.plane.read_result(task_id)

    def grant_approval(self, scope, **opts):
        return self.plane.grant_approval(scope, **opts)


def default_client():
    """The pre-G1 stand-in for an MCP client: the same three tool names over the in-process plane."""
    from main import build_plane
    return _SimulatedEditClient(build_plane("simulated"))


def _resolve_node(node: str | None = None) -> str:
    return node or os.environ.get("GUIBRIDGE_NODE") or shutil.which("node") or "node"


def run_demo(client, workspace: Path | str, node: str | None = None, task: str | None = None,
             allow: list[str] | None = None, approval_token: str | None = None,
             verifier: Verifier | None = None) -> dict:
    """Build the demo task package and hand it to `client`.

    The caller supplies `approval_token` (see `approve_forcing_manual`) when it wants the loop to
    close on its own; without it, a session still on auto-approval stops in `awaiting_approval`,
    which is what a live run does until a human acts.
    """
    package = TaskPackage(project_path=str(workspace), task=task or TASK_TEXT,
                          allow_files=allow or ["index.html", "tests/"],
                          test_commands=[[_resolve_node(node), "--test", "tests/*.test.mjs"]])
    return handoff(client, package, store=client.store, window_id=client.window_id,
                   verifier=verifier, approval_token=approval_token)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GUIBridge S3 handoff demo")
    parser.add_argument("--workspace", help="isolated git repo; created from examples/demo-app if absent")
    parser.add_argument("--node", help="node executable for the acceptance command")
    parser.add_argument("--task", help="task text; defaults to the password-toggle demo task")
    parser.add_argument("--allow", action="append", default=[],
                        help="path the change is allowed to touch; repeatable")
    parser.add_argument("--report", help="write the full JSON report here")
    parser.add_argument("--mode", choices=("simulated", "live"), default="simulated")
    cli = parser.parse_args(argv)

    if cli.mode == "live":
        raise SystemExit("live handoff drives Trae through the MCP client and needs gate G1; "
                         "see tests/test_live_handoff.py")

    workspace = prepare_workspace(cli.workspace)
    client = default_client()
    report = run_demo(client, workspace, node=cli.node, task=cli.task, allow=cli.allow or None,
                      approval_token=approve_forcing_manual(client))
    print(json.dumps({"workspace": str(workspace), "task_id": report["task_id"],
                      "states": report["states"], "reply_untrusted": report["reply"]["untrusted"],
                      "changed_files": report["verification"]["changed_files"],
                      "final_state": report["final_state"],
                      "reasons": report["verification"]["reasons"]}, ensure_ascii=False, indent=2))
    if cli.report:
        Path(cli.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["final_state"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())

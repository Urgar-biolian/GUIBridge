"""Independent verifier: Git diff scope + test commands. Trae claims are never proof.

Trust boundary (docs/agent.md): the verifier is the only actor allowed to lift a task to `verified`,
and it reads exactly two things — the repository's own state and the exit code of the acceptance
commands the *planning side* chose. The assistant reply is untrusted data and never reaches this
module, which is why acceptance commands are executed as argv lists without a shell: a sentence
coming out of the chat panel cannot be reassembled into a command line here.

Merged surface. Built with a repository, an allow-list and a test command — the shape the perception
lane and the demos use — the same object answers a bare `verify()`. Built with only a runner, it is
the stateless verifier the control plane calls with explicit paths. `verify()` returns one report
either way, and when a store and task id are configured it records the run and writes the task state
as the verifier actor, which is the only actor the store accepts for `verified`.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

# `git status --porcelain` single-letter codes; `??` marks untracked, which is what an agent that
# never commits produces. XY is read as one code: the worktree column when it is set, else the index.
_STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "renamed", "T": "modified",
           "U": "unmerged", "?": "untracked"}

OUTPUT_TAIL = 4000
TEST_OUTPUT_TAIL = 2000


def _run(argv, cwd: str, timeout: int | None = None):
    """A command that timed out is a failing command (exit 124); a command that cannot start at all
    is left to raise, because that is a missing toolchain rather than a red test."""
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return completed.returncode, completed.stdout, completed.stderr


def _argv(command) -> list[str]:
    """Accept an argv list or a command string, but never hand anything to a shell.

    Strings are split with `posix=False` because a Windows path such as `C:\\tools\\node.exe` must
    keep its backslashes; an argv list needs no splitting and is what the planner should prefer.
    """
    if isinstance(command, list):
        argv = list(command)
    else:
        argv = [part[1:-1] if len(part) > 1 and part[0] in "\"'" and part[-1] == part[0] else part
                for part in shlex.split(str(command), posix=False)]
    if not argv or any(not str(part).strip() for part in argv):
        raise ValueError(f"refusing to run an empty command: {command!r}")
    return [str(part) for part in argv]


def _tail(text: str, limit: int = OUTPUT_TAIL) -> str:
    return text[-limit:] if text and len(text) > limit else (text or "")


class Verifier:
    def __init__(self, repo=None, allowed_files=None, test_command=None, timeout: int = 180,
                 store=None, task_id: str | None = None, runner=None):
        """`repo`/`allowed_files`/`test_command` configure a verifier for one task; leave them out
        and every method takes them per call, which is how the control plane uses it."""
        self.runner = runner or (lambda argv, cwd: _run(argv, cwd, timeout))
        self.timeout = timeout
        self.repo = Path(repo) if repo is not None else None
        self.allowed_files = [str(p).replace("\\", "/").lstrip("./") for p in (allowed_files or [])]
        self.test_command = list(test_command or [])
        self.store = store
        self.task_id = task_id

    def _repo(self, repo_path) -> str:
        chosen = repo_path if repo_path is not None else self.repo
        if chosen is None:
            raise ValueError("this verifier was not configured with a repository; pass repo_path")
        return str(chosen)

    def git(self, repo_path, *args: str):
        path = self._repo(repo_path)
        return self.runner(["git", "--no-pager", "-C", path, *args], path)

    def changed_files(self, repo_path=None, since_rev: str | None = None) -> dict:
        """Working-tree changes, plus anything the executor already committed since `since_rev`."""
        repo_path = self._repo(repo_path)
        code, porcelain, stderr = self.git(repo_path, "status", "--porcelain=v1", "--untracked-files=all")
        if code != 0:
            raise RuntimeError(f"git status failed in {repo_path}: {_tail(stderr)}")
        buckets = {"added": [], "modified": [], "deleted": [], "renamed": [], "untracked": [],
                   "unmerged": []}
        for line in porcelain.splitlines():
            if not line.strip():
                continue
            status = line[:2].strip()[-1]
            path = line[3:].split(" -> ")[-1].strip('"')
            buckets[_STATUS.get(status, "modified")].append(path)
        committed = []
        if since_rev:
            code, out, err = self.git(repo_path, "diff", "--name-only", f"{since_rev}..HEAD")
            if code != 0:
                raise RuntimeError(f"git diff {since_rev}..HEAD failed: {_tail(err)}")
            committed = [path for path in out.splitlines() if path.strip()]
        changed = sorted(set(sum(buckets.values(), [])).union(committed))
        return {"buckets": buckets, "changed": changed, "committed_since": committed}

    def run_tests(self, repo_path=None, test_commands=None) -> list[dict]:
        commands = list(test_commands if test_commands is not None else self.test_command)
        repo_path = self._repo(repo_path)
        results = []
        for command in commands:
            try:
                argv = _argv(command)
            except ValueError as exc:
                results.append({"command": [str(command)], "returncode": None, "passed": False,
                                "error": str(exc)})
                continue
            try:
                code, out, err = self.runner(argv, repo_path)
            except OSError as exc:
                results.append({"command": argv, "returncode": None, "passed": False,
                                "error": f"could not run: {exc}"})
                continue
            results.append({"command": argv, "returncode": code, "passed": code == 0,
                            "stdout_tail": _tail(out), "stderr_tail": _tail(err)})
        return results

    def verify(self, repo_path=None, allow_files=None, test_commands=None, since_rev: str | None = None,
               claimed_reply: str | None = None) -> dict:
        """Returns `verified` only when scope and tests both hold; every other outcome is `failed`.

        A reply from the chat panel may be passed as `claimed_reply`; it is copied into the report
        labelled untrusted and never read here.
        """
        repo_path = self._repo(repo_path)
        reasons: list[str] = []
        allow = sorted(set(self.allowed_files if allow_files is None else allow_files))
        tests = list(self.test_command if test_commands is None else test_commands)

        state = self.changed_files(repo_path, since_rev)
        changed = state["changed"]
        out_of_scope = [path for path in changed if allow and not self._allowed(path, allow)]
        if out_of_scope:
            reasons.append("out_of_scope: " + ", ".join(out_of_scope))
        if not changed:
            reasons.append("no_changes: the executor claimed progress but the repository is untouched")

        results = self.run_tests(repo_path, tests)
        if not tests:
            reasons.append("no_acceptance_tests: nothing was configured to run, so nothing is proven")
        reasons += [f"test_error: {result['command']} {result['error']}"
                    for result in results if "error" in result]
        reasons += [f"test_failed: {json.dumps(result['command'])} exited {result['returncode']}"
                    for result in results if not result["passed"] and "error" not in result]

        _, head, _ = self.git(repo_path, "rev-parse", "HEAD")
        _, diff_stat, _ = self.git(repo_path, "diff", "--stat", "HEAD")
        status = "verified" if not reasons else "failed"
        report = {"status": status, "verified": status == "verified", "reasons": reasons,
                  "reason": self._reason(reasons), "repo_path": repo_path, "head": head.strip(),
                  "since_rev": since_rev, "changed_files": changed, "changes": state["buckets"],
                  "committed_since": state["committed_since"], "out_of_scope": out_of_scope,
                  "allow_files": allow, "tests": results, "test_exit": self._test_exit(results),
                  "test_output_tail": _tail(self._joined_output(results), TEST_OUTPUT_TAIL),
                  "diff_stat": _tail(diff_stat, TEST_OUTPUT_TAIL).strip(),
                  "claimed_reply_untrusted": claimed_reply,
                  "evidence": {"porcelain_changed": changed, "diff_stat": _tail(diff_stat),
                               "test_exit_codes": [result["returncode"] for result in results]}}
        if self.store is not None and self.task_id:
            event_id = self.store.record("verifier_run", {
                "verified": report["verified"], "reason": report["reason"], "changed_files": changed,
                "out_of_scope": out_of_scope, "test_exit": report["test_exit"], "reasons": reasons},
                task_id=self.task_id)
            self.store.set_task_state(self.task_id, "verified" if report["verified"] else "failed",
                                      event_id, actor="verifier")
            report["evidence_id"] = event_id
        return report

    #: One word for the same judgement, in the order a reader asks about it.
    _PRIORITY = (("no_changes", "no_change"), ("out_of_scope", "out_of_scope_change"),
                 ("test_failed", "tests_failed"), ("test_error", "tests_failed"),
                 ("no_acceptance_tests", "tests_failed"))

    @classmethod
    def _reason(cls, reasons: list[str]) -> str:
        for prefix, word in cls._PRIORITY:
            if any(reason.startswith(prefix) for reason in reasons):
                return word
        return "verified"

    @staticmethod
    def _test_exit(results: list[dict]) -> int | None:
        if not results:
            return None
        codes = [result["returncode"] for result in results]
        failing = [code for code in codes if code not in (None, 0)]
        return failing[0] if failing else (codes[0] if codes[0] is not None else 127)

    @staticmethod
    def _joined_output(results: list[dict]) -> str:
        return "".join(f"{result.get('stdout_tail', '')}{result.get('stderr_tail', '')}"
                       f"{result.get('error', '')}" for result in results)

    @staticmethod
    def _allowed(path: str, allow: list[str]) -> bool:
        """`src/` allows that subtree, `src/app.js` allows that file only (no glob surprises)."""
        for pattern in allow:
            if pattern.endswith("/") and path.startswith(pattern):
                return True
            if pattern == path or pattern == f"./{path}":
                return True
        return False

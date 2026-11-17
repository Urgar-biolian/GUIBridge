"""Independent verifier: Git diff scope + test commands. Trae claims are never proof.

Trust boundary (docs/agent.md): the verifier is the only actor allowed to lift a task to `verified`,
and it reads exactly two things — the repository's own state and the exit code of the acceptance
commands the *planning side* chose. The assistant reply is untrusted data and never reaches this
module, which is why acceptance commands are executed as argv lists without a shell: a sentence
coming out of the chat panel cannot be reassembled into a command line here.
"""

import json
import shlex
import subprocess

# `git status --porcelain` single-letter codes; `??` marks untracked, which is what an agent that
# never commits produces. XY is read as one code: the worktree column when it is set, else the index.
_STATUS = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "renamed", "T": "modified",
           "U": "unmerged", "?": "untracked"}

OUTPUT_TAIL = 4000


def _run(argv, cwd: str):
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
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
    def __init__(self, runner=_run):
        self.runner = runner

    def git(self, repo_path: str, *args: str) -> tuple[int, str, str]:
        return self.runner(["git", "--no-pager", "-C", repo_path, *args], repo_path)

    def changed_files(self, repo_path: str, since_rev: str | None = None) -> dict:
        """Working-tree changes, plus anything the executor already committed since `since_rev`."""
        repo_path = str(repo_path)
        code, porcelain, stderr = self.git(repo_path, "status", "--porcelain=v1", "--untracked-files=all")
        if code != 0:
            raise RuntimeError(f"git status failed in {repo_path}: {_tail(stderr)}")
        buckets = {"added": [], "modified": [], "deleted": [], "renamed": [], "untracked": [],
                   "unmerged": []}
        for line in porcelain.splitlines():
            if not line.strip():
                continue
            code = line[:2].strip()[-1]
            path = line[3:].split(" -> ")[-1]
            buckets[_STATUS.get(code, "modified")].append(path)
        committed = []
        if since_rev:
            code, out, err = self.git(repo_path, "diff", "--name-only", f"{since_rev}..HEAD")
            if code != 0:
                raise RuntimeError(f"git diff {since_rev}..HEAD failed: {_tail(err)}")
            committed = [path for path in out.splitlines() if path.strip()]
        changed = sorted(set(sum(buckets.values(), [])).union(committed))
        return {"buckets": buckets, "changed": changed, "committed_since": committed}

    def run_tests(self, repo_path: str, test_commands: list) -> list[dict]:
        results = []
        for command in test_commands:
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

    def verify(self, repo_path: str, allow_files: list[str], test_commands: list[str],
               since_rev: str | None = None) -> dict:
        """Returns `verified` only when scope and tests both hold; every other outcome is `failed`."""
        reasons: list[str] = []
        repo_path = str(repo_path)
        allow = sorted(set(allow_files or []))
        tests = [command for command in (test_commands or [])]

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
        return {"status": status, "verified": status == "verified", "reasons": reasons,
                "repo_path": repo_path, "head": head.strip(), "since_rev": since_rev,
                "changed_files": changed, "changes": state["buckets"],
                "committed_since": state["committed_since"], "out_of_scope": out_of_scope,
                "allow_files": allow, "tests": results,
                "evidence": {"porcelain_changed": changed, "diff_stat": _tail(diff_stat),
                             "test_exit_codes": [result["returncode"] for result in results]}}

    @staticmethod
    def _allowed(path: str, allow: list[str]) -> bool:
        """`src/` allows that subtree, `src/app.js` allows that file only (no glob surprises)."""
        for pattern in allow:
            if pattern.endswith("/") and path.startswith(pattern):
                return True
            if pattern == path or pattern == f"./{path}":
                return True
        return False

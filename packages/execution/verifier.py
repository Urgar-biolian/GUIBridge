"""Independent verifier: trusts only git state and test exit codes, never agent claims."""

from __future__ import annotations

import subprocess
from pathlib import Path


class Verifier:
    def __init__(self, repo: str | Path, allowed_files: list[str],
                 test_command: list[str], timeout: int = 180, store=None, task_id: str | None = None):
        self.repo = Path(repo)
        self.allowed_files = [p.replace("\\", "/").lstrip("./") for p in allowed_files]
        self.test_command = list(test_command)
        self.timeout = timeout
        self.store = store
        self.task_id = task_id

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)

    def changed_files(self) -> list[str]:
        out = self._git("status", "--porcelain").stdout or ""
        files: list[str] = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip().strip('"').replace("\\", "/")
            if path and path not in files:
                files.append(path)
        return files

    def run_tests(self) -> tuple[int, str]:
        try:
            proc = subprocess.run(self.test_command, cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 127, f"test command failed to run: {e}"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def verify(self, claimed_reply: str | None = None) -> dict:
        changed = self.changed_files()
        out_of_scope = [p for p in changed if p not in self.allowed_files]
        code, output = self.run_tests()
        tests_passed = code == 0
        if not changed:
            reason = "no_change"
        elif out_of_scope:
            reason = "out_of_scope_change"
        elif not tests_passed:
            reason = "tests_failed"
        else:
            reason = "verified"
        verified = reason == "verified"
        diff = self._git("diff", "--stat", "HEAD").stdout or ""
        result = {
            "verified": verified,
            "reason": reason,
            "changed_files": changed,
            "out_of_scope": out_of_scope,
            "test_exit": code,
            "test_output_tail": output[-2000:],
            "diff_stat": diff.strip(),
            "claimed_reply_untrusted": claimed_reply,
            "evidence": {"repo": str(self.repo), "allowed_files": self.allowed_files,
                         "test_command": self.test_command},
        }
        if self.store is not None and self.task_id:
            event_id = self.store.record("verifier_run", {
                "verified": verified, "reason": reason, "changed_files": changed,
                "out_of_scope": out_of_scope, "test_exit": code,
            }, task_id=self.task_id)
            self.store.transition(self.task_id, "verified" if verified else "failed", event_id)
            result["evidence_id"] = event_id
        return result

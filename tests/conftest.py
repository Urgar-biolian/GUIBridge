import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "apps" / "desktop-agent"))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "trae"

# Passed per command, never written into a repository's config: a test must not touch git identity.
GIT_IDENTITY = ("-c", "user.name=GUIBridge Test", "-c", "user.email=test@guibridge.local")


class ScratchRepo:
    """A throwaway git repository, which is the only kind the verifier and handoff may be tested on."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def run(self, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=str(self.path), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
        return done.stdout.strip()

    def write(self, rel: str, text: str) -> "ScratchRepo":
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return self

    def remove(self, rel: str) -> "ScratchRepo":
        (self.path / rel).unlink()
        return self

    def commit(self, message: str) -> str:
        self.run("add", "-A")
        self.run(*GIT_IDENTITY, "commit", "-m", message)
        return self.head()

    def head(self) -> str:
        return self.run("rev-parse", "HEAD")


@pytest.fixture
def scratch_repo(tmp_path):
    repo = ScratchRepo(tmp_path / "repo")
    repo.path.mkdir()
    repo.run("init", "-b", "main")
    repo.write("src/app.js", "export const value = 1;\n").write("README.md", "demo\n").write(
        "tests/password-toggle.test.mjs", 'import test from "node:test";\ntest("toggle", () => {});\n')
    repo.commit("seed")
    return repo


@pytest.fixture
def fixture_dom():
    return json.loads((FIXTURE_DIR / "dom_ide_idle.json").read_text(encoding="utf-8"))


class Recorder:
    """Verifier runner for tests: answers `git` for real so scope checks stay honest, and records the
    acceptance-command argv instead of executing it, which is what keeps a test toolchain-free."""

    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.executed = []

    def __call__(self, argv, cwd):
        if argv[0] == "git":
            done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
            return done.returncode, done.stdout, done.stderr
        self.executed.append(list(argv))
        outcome = self.outcomes.pop(0) if self.outcomes else (0, "ok\n", "")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def verifier(recorder):
    from execution.verifier import Verifier
    return Verifier(runner=recorder)


@pytest.fixture
def store():
    from events.store import EventStore
    with EventStore(":memory:") as opened:
        yield opened


@pytest.fixture
def plane():
    from main import build_plane
    return build_plane("simulated")


@pytest.fixture
def grant_approval():
    """Mirror the Dashboard approval round-trip a human would perform."""
    def _grant(plane, semantic_id: str, action: str) -> str:
        for request in plane.store.pending_approvals():
            scope = request["payload"]["scope"]
            if semantic_id in scope.get("semantic_ids", []) and action in scope.get("actions", []):
                return plane.store.grant_approval(scope, request_id=request["payload"]["request_id"])
        raise AssertionError(f"no pending approval request for {semantic_id}/{action}")
    return _grant

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
sys.path.insert(0, str(ROOT / "packages"))

from execution.verifier import Verifier  # noqa: E402
from handoff_demo import bootstrap_worktree  # noqa: E402

TEST_CMD = ["node", "--test", "tests/password.test.mjs"]


@pytest.fixture()
def repo(tmp_path):
    return bootstrap_worktree(ROOT / "examples" / "demo-app", tmp_path / "repo")


def edit(repo: Path, rel: str, old: str, new: str):
    path = repo / rel
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def test_claimed_done_without_change_is_failed(repo):
    result = Verifier(repo, ["index.html"], TEST_CMD).verify()
    assert result["verified"] is False
    assert result["reason"] == "no_change"


def test_out_of_scope_change_is_failed(repo):
    edit(repo, "src/password.js", 'return "•".repeat', 'return "-".repeat')
    result = Verifier(repo, ["index.html"], TEST_CMD).verify()
    assert result["verified"] is False
    assert result["reason"] == "out_of_scope_change"
    assert result["out_of_scope"] == ["src/password.js"]


def test_failing_tests_in_scope_are_failed(repo):
    edit(repo, "src/password.js", "if (visible)", "if (!visible)")
    result = Verifier(repo, ["src/password.js"], TEST_CMD).verify()
    assert result["verified"] is False
    assert result["reason"] == "tests_failed"
    assert result["test_exit"] != 0


def test_in_scope_change_with_green_tests_is_verified(repo):
    edit(repo, "index.html", "</label>", "</label>\n      <button>toggle</button>")
    result = Verifier(repo, ["index.html"], TEST_CMD).verify(claimed_reply="done")
    assert result["verified"] is True
    assert result["reason"] == "verified"
    assert result["changed_files"] == ["index.html"]
    assert result["claimed_reply_untrusted"] == "done"

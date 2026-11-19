"""Safety guards for the gated R5 send_task measurement instrument.

The instrument can send a live write to real Trae, so its default-refuse gate and
its fixed harmless message are locked here. These tests exercise ONLY the refusal
path and module constants — no live write, no CDP connection, no authorization.
The live measurement itself remains pending fresh R5 authorization."""

import importlib.util
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "src" / "probe" / "verify_trae_send_focus.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_trae_send_focus", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refuses_live_write_without_authorization():
    proc = subprocess.run(
        [sys.executable, str(PROBE)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 3
    assert "REFUSED" in proc.stdout
    assert "No message was sent" in proc.stdout


def test_fixed_message_is_harmless_ok_request():
    mod = _load_module()
    assert mod.FIXED_MESSAGE == "请只回复 OK 两个字母，不要执行任何其他操作。"


def test_authorized_without_project_path_aborts():
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--authorize-live-write"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "--project-path" in proc.stdout
    assert "No message was sent" not in proc.stdout  # past the refuse gate, but aborted pre-send


def test_authorized_non_git_project_path_aborts(tmp_path):
    nongit = tmp_path / "nongit"
    nongit.mkdir()
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--authorize-live-write", "--project-path", str(nongit)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "git repo" in proc.stdout


def test_is_git_repo_helper(tmp_path):
    mod = _load_module()
    nongit = tmp_path / "nongit"
    nongit.mkdir()
    assert mod._is_git_repo(str(nongit)) is False
    repo_root = Path(__file__).resolve().parents[1]
    assert mod._is_git_repo(str(repo_root)) is True
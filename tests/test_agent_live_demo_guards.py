"""Safety guards on the REAL agent live demo runner — no live write, no CDP needed.

Locks: refusal gate without --authorize-live-agent; hard block on the real project
basename; git-repo precondition; demo-page selection by title with NO fallback to the
first Trae page (which could be the real project)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

import agent_live_demo as ald  # noqa: E402
from adapters.trae.adapter import AdapterError  # noqa: E402


def _page(title):
    return SimpleNamespace(type="page", title=title, url="vscode-file://x", ws_url="ws://x")


def test_refusal_gate_without_authorize(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["agent_live_demo.py", "--project-path", "D:/QoderTest/guibridge-demo-workspace"])
    assert ald.main() == 3


def test_real_project_basename_hard_blocked(tmp_path):
    repo = tmp_path / "Agui"
    repo.mkdir()
    with pytest.raises(AdapterError) as ei:
        ald.run(repo)
    assert ei.value.code == "conflict"


def test_is_git_repo_positive_negative(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert ald._is_git_repo(plain) is False
    subprocess.run(["git", "-C", str(plain), "init", "-q"], check=True, capture_output=True)
    assert ald._is_git_repo(plain) is True


def test_select_demo_title_picks_demo_not_first_agui(monkeypatch):
    monkeypatch.setattr(ald, "list_targets",
                        lambda port: [_page("Agui - TRAE"), _page("guibridge-demo-workspace - TRAE")])
    assert ald._select_demo_title("guibridge-demo-workspace") == "guibridge-demo-workspace - TRAE"


def test_select_demo_title_refuses_when_only_real_project(monkeypatch):
    monkeypatch.setattr(ald, "list_targets", lambda port: [_page("Agui - TRAE")])
    with pytest.raises(SystemExit) as ei:
        ald._select_demo_title("guibridge-demo-workspace")
    assert ei.value.code == 2


def test_demo_adapter_target_no_fallback(monkeypatch):
    monkeypatch.setattr(ald, "list_targets", lambda port: [_page("Agui - TRAE")])
    adapter = ald.DemoAdapter(9222, None, "guibridge-demo-workspace")
    import asyncio
    with pytest.raises(AdapterError) as ei:
        asyncio.run(adapter._target())
    assert ei.value.code == "locator_missing"


def test_demo_adapter_target_selects_demo(monkeypatch):
    demo = _page("guibridge-demo-workspace - TRAE")
    monkeypatch.setattr(ald, "list_targets", lambda port: [_page("Agui - TRAE"), demo])
    adapter = ald.DemoAdapter(9222, None, "guibridge-demo-workspace")
    import asyncio
    assert asyncio.run(adapter._target()) is demo
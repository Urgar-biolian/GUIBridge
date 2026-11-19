"""The MCP-surface handoff demo: real git worktree, real verifier, real node acceptance command.

`examples/handoff_demo.py` (the plane path) is covered by tests/test_handoff.py; this file only pins
that the frozen tool names carry the same chain and that the untrusted reply is never executed.
"""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

try:
    from mcp.shared.memory import create_connected_server_and_client_session  # noqa: F401
except (ImportError, ModuleNotFoundError):
    pytest.skip("the MCP gateway demo needs the mcp 1.x SDK (pip install 'mcp<2')",
                allow_module_level=True)

if not shutil.which("node"):
    pytest.skip("`node` is not on PATH, so the acceptance command has nothing to run",
                allow_module_level=True)

from handoff_mcp_demo import run_demo  # noqa: E402


def test_simulated_handoff_reaches_verified(tmp_path):
    summary = run_demo(tmp_path)
    assert summary["transitions"][:3] == ["submitted", "running", "claimed_done"]
    assert summary["transitions"][-1] == "verified"
    assert summary["reply_untrusted"] is True
    assert summary["reply_executed"] is False
    assert summary["verified"]["verified"] is True
    assert summary["verified"]["changed_files"] == ["index.html"]

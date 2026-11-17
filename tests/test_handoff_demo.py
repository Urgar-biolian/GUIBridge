import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

from handoff_demo import run_demo  # noqa: E402


def test_simulated_handoff_reaches_verified(tmp_path):
    summary = run_demo(tmp_path)
    assert summary["transitions"][:3] == ["submitted", "running", "claimed_done"]
    assert summary["transitions"][-1] == "verified"
    assert summary["reply_untrusted"] is True
    assert summary["reply_executed"] is False
    assert summary["verified"]["verified"] is True
    assert summary["verified"]["changed_files"] == ["index.html"]

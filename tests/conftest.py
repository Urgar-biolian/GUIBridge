import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "apps" / "desktop-agent"))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "trae"


@pytest.fixture
def fixture_dom():
    return json.loads((FIXTURE_DIR / "dom_ide_idle.json").read_text(encoding="utf-8"))


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

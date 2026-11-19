"""A lane's REST contract, asserted against the merged control plane (docs/api.md §2).

`test_desktop_agent_api.py` owns the plane's behaviour; this file keeps what the perception lane
published as its planner-facing contract — the stage marker, the response keys, the flat approval
body, the heal-review body, the SSE resume, and which failure becomes which status — and runs it
through the real `build_plane("simulated")` instead of A's in-process `FakeEngine`. A fake engine
could not fail closed, which is exactly what the merged gates are for.
"""

import pytest
from fastapi.testclient import TestClient

from main import build_plane, create_app

TASK = "请只回复 OK 两个字母，不要执行任何其他操作。"


@pytest.fixture()
def plane():
    return build_plane("simulated", db_path=":memory:")


@pytest.fixture()
def client(plane):
    with TestClient(create_app(plane, plane.store)) as opened:
        yield opened


def test_health_reports_the_stage_the_docs_promise(client, plane):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stage"] == "s2"
    assert body["window_id"] == plane.window_id, "a planner needs to know which window the plane owns"


def test_windows_lists_the_identity_rows_with_their_whitelist_state(client, plane):
    plane.store.register_window("second-trae", "Trae.exe", "Other - TRAE", {})
    listed = client.get("/windows", params={"all": "true"}).json()["windows"]
    assert {entry["window_id"] for entry in listed} == {plane.window_id, "second-trae"}
    assert next(entry for entry in listed if entry["window_id"] == plane.window_id)["whitelisted"] is True
    assert next(entry for entry in listed if entry["window_id"] == "second-trae")["whitelisted"] is False


def test_a_flat_approval_body_still_grants_a_window_pinned_token(client, plane):
    """The perception lane published `{semantic_id, action}`; it may not mint a scope-free token."""
    granted = client.post("/approvals", json={"semantic_id": "trae.chat.approval_mode",
                                              "action": "click"}).json()
    assert granted["token"] and granted["scope"]["window_id"] == plane.window_id


def test_a_task_submits_and_reads_back_as_untrusted_text(client):
    created = client.post("/tasks", json={"project_path": ".", "task": TASK,
                                          "allow_auto_approval": True}).json()
    assert created["task_id"] and created["state"] == "submitted"
    assert client.get(f"/tasks/{created['task_id']}").json()["transitions"][0]["state"] == "submitted"

    result = client.get(f"/tasks/{created['task_id']}/result").json()
    assert result["reply_text"] and result["untrusted"] is True
    # A reply is a claim, never a verdict: nothing read over HTTP may arrive as `verified`.
    assert result.get("claimed_done") in (True, False)


def test_an_unknown_task_is_424_rather_than_an_invented_state(client):
    response = client.get("/tasks/nope")
    assert response.status_code == 424
    assert response.json()["error_code"] == "unknown_state"


def test_a_window_the_gate_does_not_allow_is_a_403_envelope(client, plane):
    plane.safety.allowed_windows.discard(plane.window_id)

    response = client.post("/tasks", json={"project_path": ".", "task": TASK})
    assert response.status_code == 403
    assert response.json()["error_code"] == "window_not_allowed"


def test_heal_review_takes_a_decision_and_says_who_made_it(client, plane):
    plane.store.register_heal_patch("p1", "trae.chat.composer", "trae", plane.adapter.app_version,
                                    [{"cdp_selector": ".chat-input-v2-input-box-editable"}])
    body = client.post("/locators/trae.chat.composer/heal-review",
                       json={"patch_id": "p1", "decision": "approved"}).json()
    assert body["status"] == "approved" and body["patch_id"] == "p1"

    # The perception lane's older body key (`action: "approve"`) is refused, not read as consent.
    refused = client.post("/locators/trae.chat.composer/heal-review",
                          json={"patch_id": "p1", "action": "approve"})
    assert refused.status_code == 422 and refused.json()["error_code"] == "invalid_request"


def _sse_lines(client, params):
    """The stream has no end, so a reader takes what it needs and closes it."""
    with client.stream("GET", "/events", params=params) as response:
        lines = []
        for line in response.iter_lines():
            if line.startswith(("id: ", "data: ")):
                lines.append(line)
            if len(lines) >= 2:
                break
    return lines


def test_the_event_stream_publishes_the_id_a_client_resumes_from(client):
    client.post("/tasks", json={"project_path": ".", "task": TASK, "allow_auto_approval": True})
    first = _sse_lines(client, {"limit": 1})
    assert first[0].startswith("id: ")

    resumed = _sse_lines(client, {"limit": 50, "last_event_id": first[0][len("id: "):]})
    assert resumed[0].startswith("id: ") and resumed[0] != first[0], "the acknowledged event must not replay"
    assert any(line.startswith("data: ") for line in resumed)

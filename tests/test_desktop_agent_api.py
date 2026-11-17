"""docs/api.md §2: the loopback REST surface the Dashboard and the approval flow are built on.

Status codes are the MCP error codes translated, so a rejected task and a rejected action must look
the same to a client no matter which entry point it used.
"""

import json

import pytest
from fastapi.testclient import TestClient

import main as agent_main
from main import build_plane, create_app

TASK = "请只回复 OK 两个字母，不要执行任何其他操作。"
SCOPE = {"semantic_ids": ["trae.chat.approval_mode"], "actions": ["click"]}


@pytest.fixture
def client(plane):
    with TestClient(create_app(plane, plane.store)) as opened:
        yield opened


def approval_scope(plane, **extra):
    return {"window_id": plane.window_id, **SCOPE, **extra}


def test_health_names_the_stage_and_the_channel(client, plane):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stage"] == "s2"
    assert body["channel"] == "cdp-simulated" and body["window_id"] == plane.window_id


def test_windows_default_to_the_whitelist(client, plane):
    plane.store.register_window("second-trae", "Trae.exe", "Other - TRAE", {})
    assert [w["window_id"] for w in client.get("/windows").json()["windows"]] == [plane.window_id]
    listed = client.get("/windows", params={"all": "true"}).json()["windows"]
    assert {w["window_id"] for w in listed} == {plane.window_id, "second-trae"}
    assert next(w for w in listed if w["window_id"] == "second-trae")["whitelisted"] is False


def test_a_human_can_whitelist_a_window(client, plane):
    plane.store.register_window("second-trae", "Trae.exe", "Other - TRAE", {})
    assert client.post("/windows/second-trae/whitelist").json() == {"window_id": "second-trae",
                                                                   "whitelisted": True}
    assert plane.safety.allowed_windows >= {"trae-main", "second-trae"}
    assert "second-trae" in [w["window_id"] for w in client.get("/windows").json()["windows"]]


def test_whitelisting_an_unknown_window_is_refused(client):
    response = client.post("/windows/never-seen/whitelist")
    assert response.status_code == 403
    assert response.json()["error_code"] == "window_not_allowed"


def test_a_window_off_the_whitelist_cannot_be_inspected(client):
    response = client.get("/windows/never-seen/snapshot")
    assert response.status_code == 403 and response.json()["error_code"] == "window_not_allowed"


def test_snapshot_endpoint_returns_the_captured_summary(client, plane):
    body = client.get(f"/windows/{plane.window_id}/snapshot").json()
    assert {"snapshot_id", "ts", "elements_summary", "image_path"} <= set(body)
    assert body["elements_summary"]["count"] > 0


def test_a_task_is_blocked_until_a_human_grants_approval(client, plane):
    blocked = client.post("/tasks", json={"project_path": "p", "task": TASK, "mode": "chat"})
    assert blocked.status_code == 403 and blocked.json()["error_code"] == "approval_required"

    pending = client.get("/approvals/pending").json()["requests"]
    assert len(pending) == 1 and pending[0]["payload"]["scope"]["semantic_ids"] == SCOPE["semantic_ids"]

    granted = client.post("/approvals", json={"scope": approval_scope(plane),
                                              "request_id": pending[0]["payload"]["request_id"]})
    assert granted.status_code == 200
    token = granted.json()["token"]
    assert token and granted.json()["scope"]["window_id"] == plane.window_id

    created = client.post("/tasks", json={"project_path": "p", "task": TASK, "mode": "chat",
                                          "approval_token": token})
    assert created.status_code == 200 and created.json()["state"] == "submitted"
    assert client.get("/approvals/pending").json()["requests"] == []


def test_an_approval_request_without_a_scope_is_rejected(client):
    assert client.post("/approvals", json={"granted_by": "user"}).status_code == 422


def test_task_progress_and_result_are_readable_over_http(client, plane):
    task_id = client.post("/tasks", json={"project_path": "p", "task": TASK,
                                          "allow_auto_approval": True}).json()["task_id"]
    states = [client.get(f"/tasks/{task_id}").json()["state"] for _ in range(4)]
    assert states[0] == "running" and "claimed_done" in states

    detail = client.get(f"/tasks/{task_id}").json()
    assert [step["state"] for step in detail["transitions"]] == ["submitted", "running", "claimed_done"]
    assert detail["evidence"] and detail["signals"]["running_text"] is False

    result = client.get(f"/tasks/{task_id}/result", params={"max_chars": 3}).json()
    assert result["untrusted"] is True and result["claimed_done"] is True
    assert len(result["reply_text"]) <= 3 and result["truncated"] is True


def test_the_task_list_matches_the_store(client, plane):
    created = client.post("/tasks", json={"project_path": "p", "task": TASK,
                                         "allow_auto_approval": True}).json()
    listed = client.get("/tasks").json()["tasks"]
    assert [entry["task_id"] for entry in listed] == [created["task_id"]]
    assert listed[0]["state"] == "submitted" and listed[0]["mode"] == "chat"


def test_a_task_this_process_does_not_know_is_424(client):
    response = client.get("/tasks/task_never_created")
    assert response.status_code == 424 and response.json()["error_code"] == "unknown_state"


def test_an_incomplete_task_body_is_a_client_error(client):
    response = client.post("/tasks", json={"task": TASK})
    assert response.status_code == 422
    assert "project_path" in response.json()["message"]


def test_conflicting_candidates_surface_as_409(client, plane, monkeypatch):
    def two_matches(window_id, selector):
        return [{"selector": selector, "role": "button", "name": "a"},
                {"selector": selector, "role": "button", "name": "b"}]
    monkeypatch.setattr(plane.channel, "query", two_matches)
    response = client.post("/tasks", json={"project_path": "p", "task": TASK,
                                           "allow_auto_approval": True})
    assert response.status_code == 409 and response.json()["error_code"] == "conflict"


def test_the_registry_and_its_heal_review_are_exposed(client, plane):
    registry = client.get("/locators").json()
    assert len(registry["locators"]) == 8 and registry["heal_patches"] == []
    assert {entry["semantic_id"] for entry in registry["locators"]} >= {"trae.chat.composer",
                                                                        "trae.chat.approval_mode"}

    patch_id = plane.store.propose_heal_patch("trae.chat.send_button", "trae", "3.6.13",
                                              [{"cdp_selector": ".chat-input-v2-send-button-v2"}])
    listed = client.get("/locators").json()["heal_patches"]
    assert [entry["patch_id"] for entry in listed] == [patch_id] and listed[0]["status"] == "pending"

    reviewed = client.post("/locators/trae.chat.send_button/heal-review",
                           json={"patch_id": patch_id, "decision": "approved"}).json()
    assert reviewed["status"] == "approved"
    stored = next(entry for entry in client.get("/locators").json()["locators"]
                  if entry["semantic_id"] == "trae.chat.send_button")
    assert stored["chain"] == [{"cdp_selector": ".chat-input-v2-send-button-v2"}]

    again = client.post("/locators/trae.chat.send_button/heal-review",
                        json={"patch_id": patch_id, "decision": "rejected"})
    assert again.status_code == 409 and again.json()["error_code"] == "conflict"


def test_heal_review_input_is_checked_before_it_touches_the_registry(client):
    assert client.post("/locators/trae.chat.composer/heal-review",
                       json={"decision": "approved"}).json()["error_code"] == "invalid_request"
    assert client.post("/locators/trae.chat.composer/heal-review",
                       json={"patch_id": "heal_x", "decision": "maybe"}).status_code == 422


def test_heal_review_of_a_missing_patch_is_not_found(client):
    response = client.post("/locators/trae.chat.composer/heal-review",
                           json={"patch_id": "heal_nope", "decision": "approved"})
    assert response.status_code == 404 and response.json()["error_code"] == "locator_missing"


def test_events_stream_the_audit_log_in_order(client, plane):
    client.post("/tasks", json={"project_path": "p", "task": TASK, "allow_auto_approval": True})
    with client.stream("GET", "/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        payloads = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[len("data: "):]))
                if len(payloads) >= 2:
                    break
    assert [entry["kind"] for entry in payloads[:2]] == [event["kind"] for event in
                                                         plane.store.events()[:2]]
    assert [entry["seq"] for entry in payloads] == sorted(entry["seq"] for entry in payloads)


def test_live_mode_refuses_to_start_rather_than_fake_a_desktop():
    with pytest.raises(SystemExit) as exc:
        build_plane("live")
    assert "G1" in str(exc.value)


def test_the_control_plane_binds_to_loopback_only(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as exc:
        agent_main.main()
    assert "loopback" in str(exc.value)

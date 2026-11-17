import pytest
from fastapi.testclient import TestClient

import main
from events.store import EventStore


class FakeEngine:
    def __init__(self):
        self.store = EventStore(":memory:")
        self.allowed_windows = set()

    def list_windows(self):
        return [{"window_id": "trae", "process_name": "Trae.exe", "title": "Agui - TRAE",
                 "bounds": [0, 0, 10, 10], "whitelisted": "trae" in self.allowed_windows}]

    def allow_window(self, window_id):
        self.allowed_windows.add(window_id)
        return {"window_id": window_id, "whitelisted": True}

    def send_task(self, project_path, task, mode="chat", allow_files=None, acceptance=None):
        self.store.create_task("t1", "trae", project_path, mode, acceptance)
        self.store.transition("t1", "submitted", "e1")
        return {"task_id": "t1", "app": "trae", "state": "submitted", "transitions": []}

    def read_result(self, task_id, max_chars=8000):
        return {"task_id": task_id, "reply_text": "OK", "untrusted": True,
                "claimed_done": True, "evidence": []}

    def list_locators(self):
        return [{"semantic_id": "trae.chat.composer", "app_version": "3.6.13",
                 "chain": [{"cdp_selector": ".chat-input-v2-input-box-editable"}],
                 "verification": "focusable"}]

    def get_snapshot(self, window_id):
        return {"snapshot_id": "snap_1", "elements_summary": [], "image_path": None}


@pytest.fixture()
def client():
    app = main.create_app(FakeEngine())
    return TestClient(app)


def test_health_reports_stage(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stage"] == "s2"


def test_whitelist_and_windows(client):
    assert client.post("/windows/trae/whitelist").json()["whitelisted"] is True
    windows = client.get("/windows").json()["windows"]
    assert windows[0]["whitelisted"] is True


def test_tasks_roundtrip(client):
    created = client.post("/tasks", json={"project_path": r"D:\GitHub\Agui", "task": "hi"}).json()
    assert created["task_id"] == "t1"
    task = client.get("/tasks/t1").json()
    assert task["state"] == "submitted"
    assert task["transitions"][0]["state"] == "submitted"
    assert client.get("/tasks/t1/result").json()["reply_text"] == "OK"
    assert client.get("/tasks/nope").status_code == 404


def test_approval_flow(client):
    granted = client.post("/approvals", json={"semantic_id": "trae.send_task",
                                              "action": "agent"}).json()
    assert granted["token"]
    pending = client.get("/approvals/pending").json()["approvals"]
    assert pending[0]["approval_id"] == granted["approval_id"]
    client.app.state.engine.store.consume_approval(granted["token"], "trae.send_task", "agent")
    assert client.get("/approvals/pending").json()["approvals"] == []


def test_heal_review_endpoint(client):
    client.app.state.engine.store.register_heal_patch(
        "p1", "trae.chat.composer", "trae", "3.6.13", [{"cdp_selector": ".x"}])
    body = client.post("/locators/trae.chat.composer/heal-review",
                       json={"patch_id": "p1", "action": "approve"}).json()
    assert body["status"] == "approved"


def test_error_envelope_on_engine_error():
    class BrokenEngine(FakeEngine):
        def send_task(self, *a, **k):
            raise Broken("no window")

    class Broken(RuntimeError):
        code = "window_not_allowed"

    client = TestClient(main.create_app(BrokenEngine()), raise_server_exceptions=False)
    res = client.post("/tasks", json={"project_path": "x", "task": "y"})
    assert res.status_code == 403
    assert res.json()["error_code"] == "window_not_allowed"


def test_events_route_registered(client):
    assert any(getattr(r, "path", "") == "/events" for r in client.app.routes)

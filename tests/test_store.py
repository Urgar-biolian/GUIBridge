import pytest

from events.store import ApprovalError, EventStore, StoreError


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "guibridge.db"))
    yield s
    s.close()


def test_record_and_read_events(store):
    eid = store.record("action", {"x": 1}, evidence=["snap_1"], window_id="w",
                       semantic_id="sid", action="click")
    event = store.get_event(eid)
    assert event["kind"] == "action" and event["payload"] == {"x": 1}
    assert event["evidence"] == ["snap_1"]
    batch = store.events_after()
    assert batch[-1]["event_id"] == eid


def test_events_after_cursor(store):
    e1 = store.record("a", {})
    e2 = store.record("b", {})
    assert [e["event_id"] for e in store.events_after(e1)] == [e2]


def test_task_lifecycle(store):
    store.create_task("t1", "trae", r"D:\proj", "chat", {"test_commands": ["pytest"]})
    store.transition("t1", "submitted", "evt_1")
    store.transition("t1", "running", "evt_2")
    task = store.get_task("t1")
    assert task["state"] == "running"
    assert [t["state"] for t in task["transitions"]] == ["submitted", "running"]
    assert store.list_tasks()[0]["task_id"] == "t1"


def test_snapshot_roundtrip(store):
    sid = store.add_snapshot("w", {"count": 2}, image_path=None)
    snap = store.get_snapshot(sid)
    assert snap["window_id"] == "w" and snap["elements"] == {"count": 2}


def test_approval_token_single_use(store):
    approval = store.create_approval({"semantic_id": "sid", "action": "click"})
    used = store.consume_approval(approval["token"], "sid", "click")
    assert used == approval["approval_id"]
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "sid", "click")


def test_approval_scope_mismatch(store):
    approval = store.create_approval({"semantic_id": "sid", "action": "click"})
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "other", "click")


def test_approval_expiry(store):
    approval = store.create_approval({"semantic_id": "sid", "action": "click"}, ttl_seconds=-5)
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "sid", "click")


def test_consume_scope_for_agent_task(store):
    store.create_approval({"semantic_id": "trae.send_task", "action": "agent"})
    approval_id = store.consume_scope("trae.send_task", "agent")
    assert approval_id.startswith("apr_")
    assert store.pending_approvals() == []


def test_heal_patch_review_flow(store):
    store.register_heal_patch("p1", "sid", "trae", "3.6.13", [{"cdp_selector": ".x"}])
    assert store.list_heal_patches("pending")[0]["patch_id"] == "p1"
    store.review_heal_patch("p1", "approved", "reviewer")
    assert store.list_heal_patches("approved")[0]["reviewed_by"] == "reviewer"
    with pytest.raises(StoreError):
        store.review_heal_patch("p1", "rejected", "reviewer")


def test_prune_keeps_task_events(store):
    orphan = store.record("noise", {})
    store.create_task("t1", "trae", "p", "chat")
    keep = store.record("signal", {}, task_id="t1")
    store._conn.execute("UPDATE events SET ts='2000-01-01T00:00:00+00:00'")
    store._conn.commit()
    assert store.prune() == 1
    remaining = [e["event_id"] for e in store.events_after()]
    assert orphan not in remaining and keep in remaining
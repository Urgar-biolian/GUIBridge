import pytest

from events.store import ApprovalError, EventStore


def window(store, window_id="w1", whitelisted=True):
    store.register_window(window_id, "Trae.exe", "Agui - TRAE", {"x": 0, "y": 0}, whitelisted=whitelisted)
    return window_id


def test_schema_is_applied_and_versioned(store):
    row = store.conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == 1


def test_events_are_append_only_and_ordered_by_arrival(store):
    window(store)
    first = store.record("action", {"n": 1}, window_id="w1")
    second = store.record("action", {"n": 2}, window_id="w1")
    events = store.events()
    assert [e["event_id"] for e in events] == [first, second]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert store.get_event(first)["payload"] == {"n": 1}


def test_event_filters(store):
    window(store, "w1")
    window(store, "w2")
    store.record("action", {"a": 1}, window_id="w1")
    store.record("snapshot", {"a": 2}, window_id="w2")
    assert [e["kind"] for e in store.events(window_id="w2")] == ["snapshot"]
    assert store.events(kind="action", limit=10)[0]["window_id"] == "w1"


def test_snapshot_requires_a_registered_window(store):
    with pytest.raises(Exception):
        store.add_snapshot("ghost", [{"selector": ".x"}])


def test_snapshot_roundtrip(store):
    window(store)
    snapshot_id = store.add_snapshot("w1", [{"selector": ".a"}], "evidence/a.png")
    loaded = store.get_snapshot(snapshot_id)
    assert loaded["image_path"] == "evidence/a.png"
    assert loaded["elements"] == [{"selector": ".a"}]


def test_task_state_requires_known_state(store):
    window(store)
    store.create_task("t1", "trae", "D:/repo")
    with pytest.raises(ValueError):
        store.set_task_state("t1", "done-ish", "ev")


def test_transitions_append_and_update_the_task_row(store):
    store.create_task("t1", "trae", "D:/repo")
    store.set_task_state("t1", "submitted", "ev1")
    store.set_task_state("t1", "running", "ev2")
    assert store.get_task("t1")["state"] == "running"
    assert [t["state"] for t in store.task_transitions("t1")] == ["submitted", "running"]


def test_verified_is_restricted_to_the_verifier(store):
    store.create_task("t1", "trae", "D:/repo")
    with pytest.raises(PermissionError):
        store.set_task_state("t1", "verified", "ev1", actor="adapter")
    store.set_task_state("t1", "verified", "ev1", actor="verifier")
    assert store.get_task("t1")["state"] == "verified"


def test_approval_token_is_single_use_and_scoped(store):
    token = store.grant_approval({"window_id": "w1", "semantic_ids": ["trae.chat.approval_mode"],
                                  "actions": ["click"]})
    approval_id = store.consume_approval(token, "w1", "trae.chat.approval_mode", "click")
    assert approval_id
    with pytest.raises(ApprovalError) as used_again:
        store.consume_approval(token, "w1", "trae.chat.approval_mode", "click")
    assert used_again.value.code == "approval_required"


def test_approval_token_rejects_a_different_scope(store):
    token = store.grant_approval({"window_id": "w1", "semantic_ids": ["trae.chat.approval_mode"],
                                  "actions": ["click"]})
    with pytest.raises(ApprovalError):
        store.consume_approval(token, "w2", "trae.chat.approval_mode", "click")
    with pytest.raises(ApprovalError):
        store.consume_approval(token, "w1", "trae.chat.delete", "click")


def test_expired_approval_is_rejected(store):
    token = store.grant_approval({"window_id": "w1"}, ttl_seconds=-1)
    with pytest.raises(ApprovalError):
        store.consume_approval(token, "w1", "trae.chat.approval_mode", "click")


def test_pending_requests_clear_once_granted(store):
    request_id = store.request_approval({"window_id": "w1", "semantic_ids": ["trae.chat.approval_mode"],
                                         "actions": ["click"]}, "switch to manual approval")
    assert [e["payload"]["request_id"] for e in store.pending_approvals()] == [request_id]
    store.grant_approval({"window_id": "w1"}, request_id=request_id)
    assert store.pending_approvals() == []


def test_whitelist_roundtrip(store):
    window(store, "w1", whitelisted=False)
    window(store, "w2", whitelisted=True)
    assert [w["window_id"] for w in store.list_windows(True)] == ["w2"]
    store.set_whitelisted("w1", True)
    assert len(store.list_windows(True)) == 2
    with pytest.raises(KeyError):
        store.set_whitelisted("ghost", True)


def test_register_window_preserves_an_existing_whitelist_flag(store):
    window(store, "w1", whitelisted=True)
    store.register_window("w1", "Trae.exe", "Agui - TRAE", {"x": 10})
    assert store.get_window("w1")["whitelisted"] is True
    assert store.get_window("w1")["geometry"] == {"x": 10}


def test_locator_upsert_is_version_scoped(store):
    store.save_locator("trae.chat.composer", "trae", "3.6.13", [{"cdp_selector": ".a"}], "focusable")
    store.save_locator("trae.chat.composer", "trae", "3.6.13", [{"cdp_selector": ".b"}], "focusable")
    store.save_locator("trae.chat.composer", "trae", "3.7.0", [{"cdp_selector": ".c"}], "focusable")
    rows = store.list_locators(app="trae", app_version="3.6.13")
    assert len(rows) == 1 and rows[0]["chain"][0]["cdp_selector"] == ".b"
    assert len(store.list_locators(app="trae")) == 2


def test_heal_patch_review_flow(store):
    patch_id = store.propose_heal_patch("trae.chat.composer", "trae", "3.6.13", [{"cdp_selector": ".new"}])
    assert store.list_heal_patches("pending")[0]["patch_id"] == patch_id
    with pytest.raises(KeyError):
        store.review_heal_patch("nope", "approved", "me")
    with pytest.raises(ValueError):
        store.review_heal_patch(patch_id, "maybe", "me")

    store.review_heal_patch(patch_id, "rejected", "me")
    assert store.list_locators(app="trae") == []
    with pytest.raises(PermissionError):
        store.review_heal_patch(patch_id, "approved", "me")

    second = store.propose_heal_patch("trae.chat.composer", "trae", "3.6.13", [{"cdp_selector": ".new"}])
    store.review_heal_patch(second, "approved", "me")
    assert store.list_locators("trae")[0]["chain"][0]["cdp_selector"] == ".new"


def test_purge_expired_prunes_events_and_reports_images(tmp_path):
    old = "2000-01-01T00:00:00+00:00"
    store = EventStore(str(tmp_path / "ev.sqlite3"), retention_days=0)
    store.register_window("w1", "Trae.exe", "Agui - TRAE", {})
    stale = store.record("action", {"n": 1}, window_id="w1")
    snapshot_id = store.add_snapshot("w1", [], "evidence/old.png")
    store.conn.execute("UPDATE events SET ts=? WHERE event_id=?", (old, stale))
    store.conn.execute("UPDATE snapshots SET ts=? WHERE snapshot_id=?", (old, snapshot_id))
    store.conn.commit()
    fresh = store.record("action", {"n": 2}, window_id="w1")
    assert store.purge_expired() == ["evidence/old.png"]
    store.close()

    with EventStore(str(tmp_path / "ev.sqlite3")) as reopened:
        assert [e["event_id"] for e in reopened.events()] == [fresh]
        assert reopened.get_snapshot(snapshot_id) is None


def test_persistence_across_reopen(tmp_path):
    path = str(tmp_path / "ev.sqlite3")
    with EventStore(path) as first:
        first.register_window("w1", "Trae.exe", "Agui - TRAE", {})
        first.record("action", {"n": 7}, window_id="w1")
    with EventStore(path) as second:
        assert second.events()[0]["payload"] == {"n": 7}


def test_time_helpers_use_utc_offsets(store):
    stamp = store.create_task("t1", "trae", "D:/repo")["created_ts"]
    assert stamp.endswith("+00:00")

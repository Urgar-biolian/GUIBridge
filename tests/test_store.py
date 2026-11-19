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


# The A-line surface: the same rows under the names the perception lane writes with. These came over
# with it and stay as its contract tests, adapted only where the merged store deliberately behaves
# otherwise — the windows foreign key, token presentation, and a single module clock.


def test_record_event_with_evidence(store):
    window(store, "w")
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
    store.create_task("t1", "trae", "D:/proj", "chat", {"test_commands": ["pytest"]})
    store.transition("t1", "submitted", "evt_1")
    store.transition("t1", "running", "evt_2")
    task = store.get_task("t1")
    assert task["state"] == "running"
    assert [t["state"] for t in task["transitions"]] == ["submitted", "running"]
    assert store.list_tasks()[0]["task_id"] == "t1"


def test_transition_wrapper_cannot_grant_verified(store):
    """`transition` is the executor-facing name, so it carries the executor actor and nothing else."""
    store.create_task("t1", "trae", "D:/proj", "chat")
    with pytest.raises(PermissionError):
        store.transition("t1", "verified", "evt_1")
    assert store.get_task("t1")["state"] == "unknown"


def test_snapshot_accepts_a_channel_shaped_summary(store):
    window(store, "w")
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


def test_an_empty_scope_grants_nothing(store):
    approval = store.create_approval({})
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "sid", "click")


def test_approval_expiry(store):
    approval = store.create_approval({"semantic_id": "sid", "action": "click"}, ttl_seconds=-5)
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "sid", "click")


def test_expiry_follows_the_module_clock(store, monkeypatch):
    """Expiry compares against the module-level `utcnow`, so one patch moves the judgement."""
    from events import store as store_mod
    approval = store.create_approval({"semantic_id": "sid", "action": "click"})
    monkeypatch.setattr(store_mod, "utcnow", lambda: "2099-01-01T00:00:00+00:00")
    with pytest.raises(ApprovalError):
        store.consume_approval(approval["token"], "sid", "click")


def test_an_agent_task_approval_still_has_to_be_presented(store):
    """A's `consume_scope` matched a pending row without a token, which is self-authorization.

    It is not ported: the agent path presents the token the same way an operator does.
    """
    assert not hasattr(store, "consume_scope")
    approval = store.create_approval({"semantic_id": "trae.send_task", "action": "agent"})
    with pytest.raises(ApprovalError):
        store.consume_approval("", "trae.send_task", "agent")
    assert store.consume_approval(approval["token"], "trae.send_task", "agent") == approval["approval_id"]


def test_heal_patch_registration_and_review(store):
    store.register_heal_patch("p1", "sid", "trae", "3.6.13", [{"cdp_selector": ".x"}])
    assert store.list_heal_patches("pending")[0]["patch_id"] == "p1"
    store.review_heal_patch("p1", "approved", "reviewer")
    assert store.list_heal_patches("approved")[0]["reviewed_by"] == "reviewer"
    # A second decision on the same patch is refused, which is the point A's StoreError branch made.
    with pytest.raises(PermissionError):
        store.review_heal_patch("p1", "rejected", "reviewer")
    assert store.list_locators("trae")[0]["chain"][0]["cdp_selector"] == ".x"


def test_prune_keeps_task_events(store):
    orphan = store.record("noise", {})
    store.create_task("t1", "trae", "p", "chat")
    keep = store.record("signal", {}, task_id="t1")
    store.conn.execute("UPDATE events SET ts='2000-01-01T00:00:00+00:00'")
    store.conn.commit()
    assert store.prune() == 1
    remaining = [e["event_id"] for e in store.events_after()]
    assert orphan not in remaining and keep in remaining

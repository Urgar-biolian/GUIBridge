"""Evidence-persistence bridge (design 11.4 gap 3): focus snapshots -> store ids.

Uses a REAL EventStore (tmp sqlite), not a proxy, so the append-only snapshot rows
and the injected envelope ids are verified against the actual storage layer."""

import pytest

from events.store import EventStore
from packages.focusguard.evidence_bridge import persist_focus_evidence, to_api_envelope
from packages.focusguard.outcome import ActionResult, FocusSnapshot, ResultState
from packages.routing.capability import Channel, InterferenceRisk


def _snap(hwnd=100, xy=(0, 0), active=True, ts=1.0):
    return FocusSnapshot(foreground_hwnd=hwnd, cursor_xy=xy, target_active=active, ts=ts)


def _result(state=ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED, before=True, after=True):
    return ActionResult(
        state=state, channel=Channel.APP_PROTOCOL, risk=InterferenceRisk.NONE,
        effect_verified=state is not ResultState.UNCONFIRMED and state is not ResultState.FAILED,
        evidence={"note": "probe"},
        focus_before=_snap(hwnd=100) if before else None,
        focus_after=_snap(hwnd=100, ts=2.0) if after else None,
    )


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "ev.db"))
    yield s
    s.close()


def test_persist_before_after_distinct_and_readable(store):
    before, after, ids = persist_focus_evidence(_result(), "trae", store)
    assert before and after and before != after
    assert ids == [before, after]
    b = store.get_snapshot(before)["elements"]
    a = store.get_snapshot(after)["elements"]
    assert b["label"] == "before" and a["label"] == "after"
    assert b["focus"]["foreground_hwnd"] == 100
    assert b["state"] == "success_no_interference_observed"
    assert b["risk"] == "none"
    assert b["evidence"] == {"note": "probe"}


def test_to_api_envelope_injects_ids_and_preserves_state(store):
    env = to_api_envelope(_result(), "trae", store)
    assert env.success is True and env.verified is True
    assert env.state is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    assert env.before_snapshot_id and env.after_snapshot_id
    assert env.evidence == [env.before_snapshot_id, env.after_snapshot_id]
    assert env.to_dict()["state"] == "success_no_interference_observed"


def test_unconfirmed_preserved_distinct_from_failed(store):
    env = to_api_envelope(_result(state=ResultState.UNCONFIRMED), "trae", store)
    assert env.success is False and env.verified is False
    assert env.error_code is None
    assert env.state is ResultState.UNCONFIRMED
    assert env.evidence  # snapshots still persisted


def test_missing_snapshots_yield_empty_ids(store):
    before, after, ids = persist_focus_evidence(_result(before=False, after=False), "trae", store)
    assert before is None and after is None and ids == []
    env = to_api_envelope(_result(before=False, after=False), "trae", store)
    assert env.before_snapshot_id is None and env.after_snapshot_id is None
    assert env.evidence == []


def test_after_only_not_mislabelled_as_before(store):
    before, after, ids = persist_focus_evidence(_result(before=False), "trae", store)
    assert before is None and after is not None
    assert ids == [after]
    assert store.get_snapshot(after)["elements"]["label"] == "after"


def test_snapshots_append_only_across_calls(store):
    _, _, first = persist_focus_evidence(_result(), "trae", store)
    _, _, second = persist_focus_evidence(_result(), "trae", store)
    assert set(first).isdisjoint(set(second))
    assert store.get_snapshot(first[0]) is not None  # earlier rows not overwritten
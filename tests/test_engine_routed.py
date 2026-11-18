"""Opt-in engine routed send_task path (additive G1 wiring; frozen defaults untouched).

Fakes only the Win32 guard and the adapter's send effect; the capability table,
approval token flow, EventStore persistence and envelope are all real."""

from types import SimpleNamespace

import pytest

from adapters.trae.adapter import AdapterError
from engine import GUIBridgeEngine
from events.store import EventStore
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot


def _snap(ts):
    return FocusSnapshot(foreground_hwnd=100, cursor_xy=(0, 0), target_active=True, ts=ts)


class FakeGuard:
    def __init__(self):
        self.calls = 0

    def wrap_with_events(self, fn):
        self.calls += 1
        return FocusRun(result=fn(), before=_snap(1.0), after=_snap(2.0))


@pytest.fixture()
def plane(tmp_path):
    store = EventStore(str(tmp_path / "plane.db"))
    eng = GUIBridgeEngine(store=store)
    eng.allowed_windows.add("trae")
    yield eng, store
    store.close()


def _token(store):
    return store.create_approval({"semantic_id": "trae.send_task", "action": "send_task"})


def test_routed_denied_without_token(plane, monkeypatch):
    eng, store = plane
    guard = FakeGuard()
    calls = []
    monkeypatch.setattr(eng, "_focus_guard", lambda: guard)
    monkeypatch.setattr(eng.adapter, "send_task", lambda *a, **k: calls.append(1))
    res = eng.send_task_routed("D:/demo", "hi")
    assert res["executed"] is False
    assert res["denied_reason"] == "no_executable_channel"
    assert res["envelope"] is None
    assert calls == [] and guard.calls == 0


def test_routed_executes_with_approval_and_persists_evidence(plane, monkeypatch):
    eng, store = plane
    guard = FakeGuard()
    monkeypatch.setattr(eng, "_focus_guard", lambda: guard)
    monkeypatch.setattr(eng.adapter, "send_task",
                        lambda *a, **k: SimpleNamespace(task_id="t1", app="trae",
                                                        state="submitted", transitions=[]))
    apr = _token(store)
    res = eng.send_task_routed("D:/demo", "hi", approval_token=apr["token"])
    assert res["executed"] is True
    assert res["channel"] == "app_protocol"
    assert res["approval_id"] == apr["approval_id"]
    env = res["envelope"]
    assert env["success"] is True
    assert env["state"] == "success_no_interference_observed"
    assert len(env["evidence"]) == 2
    assert guard.calls == 1


def test_routed_adapter_error_is_failed(plane, monkeypatch):
    eng, store = plane
    monkeypatch.setattr(eng, "_focus_guard", lambda: FakeGuard())

    def boom(*a, **k):
        raise AdapterError("not_submitted", "composer missing")
    monkeypatch.setattr(eng.adapter, "send_task", boom)
    res = eng.send_task_routed("D:/demo", "hi", approval_token=_token(store)["token"])
    assert res["executed"] is True
    assert res["envelope"]["state"] == "failed"
    assert res["envelope"]["error_code"] == "not_submitted"


def test_routed_agent_mode_rejected(plane):
    eng, _ = plane
    with pytest.raises(AdapterError):
        eng.send_task_routed("D:/demo", "hi", mode="agent")
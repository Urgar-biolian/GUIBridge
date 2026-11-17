import pytest

from events.store import EventStore
from execution.actions import ActionExecutor
from execution.safety import SafetyGate
from semantic.element import GUIElement
from semantic.resolver import LocatorMissing


def element():
    return GUIElement(id="w:cdp:1", window_id="w", role="button", name="发送",
                      bounds=(1, 2, 30, 40), actions=["click"], source=["cdp"],
                      confidence=0.9, evidence={"cdp": {"tag": "BUTTON"}})


class FakeResolver:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def resolve(self, window_id, semantic_id):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "a.db"))
    yield s
    s.close()


def make_executor(store, resolver, actor=lambda *a: True, allowed={"w"}):
    return ActionExecutor(resolver, SafetyGate(allowed, approvals=store), store,
                          snapshotter=lambda wid: {"summary": ["x"]}, actor=actor)


def test_successful_click_records_evidence(store):
    executor = make_executor(store, FakeResolver(element()))
    result = executor.perform("w", "sid", "click")
    assert result.success and result.before_snapshot_id and result.after_snapshot_id
    event = store.events_after()[-1]
    assert event["kind"] == "action" and event["payload"]["calibrated"] is False


def test_locator_missing_returns_error_result(store):
    executor = make_executor(store, FakeResolver(error=LocatorMissing("gone")))
    result = executor.perform("w", "sid", "click")
    assert result.success is False and result.error_code == "locator_missing"
    assert store.events_after()[-1]["kind"] == "action_failed"


def test_high_impact_blocked_without_token(store):
    calls = []
    executor = make_executor(store, FakeResolver(element()), actor=lambda *a: calls.append(1) or True)
    result = executor.perform("w", "trae.chat.approval_mode", "click")
    assert result.success is False and result.error_code == "approval_required"
    assert calls == []


def test_actor_failure_is_reported(store):
    executor = make_executor(store, FakeResolver(element()), actor=lambda *a: False)
    result = executor.perform("w", "sid", "click")
    assert result.success is False and result.error_code is None
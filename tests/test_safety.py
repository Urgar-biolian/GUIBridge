import pytest

from events.store import EventStore
from execution.safety import SafetyError, SafetyGate


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "s.db"))
    yield s
    s.close()


def test_unknown_window_blocked(store):
    gate = SafetyGate({"w1"}, approvals=store)
    with pytest.raises(SafetyError) as ei:
        gate.check_action("w2", "trae.chat.send_button", "click", None)
    assert ei.value.code == "window_not_allowed"


def test_normal_action_allowed(store):
    gate = SafetyGate({"w1"}, approvals=store)
    assert gate.check_action("w1", "trae.chat.send_button", "click", None) is None


def test_high_impact_requires_token(store):
    gate = SafetyGate({"w1"}, approvals=store)
    with pytest.raises(SafetyError) as ei:
        gate.check_action("w1", "trae.chat.approval_mode", "click", None)
    assert ei.value.code == "approval_required"


def test_high_impact_with_valid_token(store):
    approval = store.create_approval({"semantic_id": "trae.chat.approval_mode", "action": "click"})
    gate = SafetyGate({"w1"}, approvals=store)
    approval_id = gate.check_action("w1", "trae.chat.approval_mode", "click", approval["token"])
    assert approval_id == approval["approval_id"]
    with pytest.raises(SafetyError):
        gate.check_action("w1", "trae.chat.approval_mode", "click", approval["token"])


def test_identity_checker_failure(store):
    def checker(wid):
        raise RuntimeError("process replaced")

    gate = SafetyGate({"w1"}, identity_checker=checker, approvals=store)
    with pytest.raises(SafetyError) as ei:
        gate.check_action("w1", "trae.chat.send_button", "click", None)
    assert ei.value.code == "identity_mismatch"
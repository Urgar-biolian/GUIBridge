import pytest

from execution.safety import (ApprovalRequired, HIGH_IMPACT, IdentityCheckFailed, SafetyError,
                              SafetyGate, is_high_impact)


@pytest.fixture
def gate(store):
    return SafetyGate({"w1"}, store)


@pytest.mark.parametrize("semantic_id", ["trae.chat.approval_mode", "trae.terminal.run", "trae.git.commit",
                                        "trae.chat.delete"])
def test_high_impact_matches_the_leaf_of_a_semantic_id(semantic_id):
    assert is_high_impact(semantic_id)


@pytest.mark.parametrize("semantic_id", ["trae.chat.composer", "trae.chat.send_button", "trae.chat.model_select"])
def test_ordinary_controls_are_not_high_impact(semantic_id):
    assert not is_high_impact(semantic_id)


def test_high_impact_table_matches_api_doc():
    assert HIGH_IMPACT == {"approval_mode", "terminal", "delete", "install", "git_commit", "git_push"}


def test_unlisted_window_is_refused(gate):
    with pytest.raises(SafetyError) as err:
        gate.check_action("w9", "trae.chat.composer", "click", None)
    assert err.value.code == "window_not_allowed"


def test_high_impact_without_token_creates_a_pending_request(gate):
    with pytest.raises(SafetyError) as err:
        gate.check_action("w1", "trae.chat.approval_mode", "click", None)
    assert err.value.code == "approval_required"
    pending = gate.store.pending_approvals()
    assert pending and pending[-1]["payload"]["scope"]["semantic_ids"] == ["trae.chat.approval_mode"]


def test_high_impact_consumes_a_granted_token(gate):
    scope = {"window_id": "w1", "semantic_ids": ["trae.chat.approval_mode"], "actions": ["click"]}
    token = gate.store.grant_approval(scope)
    assert gate.check_action("w1", "trae.chat.approval_mode", "click", token)
    with pytest.raises(SafetyError):
        gate.check_action("w1", "trae.chat.approval_mode", "click", token)


def test_a_storeless_gate_cannot_validate_tokens():
    gate = SafetyGate({"w1"})
    with pytest.raises(SafetyError) as err:
        gate.check_action("w1", "trae.chat.delete", "click", "token")
    assert err.value.code == "approval_required"


def test_identity_check_compares_process_and_title_suffix(gate):
    expected = {"window_id": "w1", "process_name": "Trae.exe", "title_suffix": " - TRAE"}
    gate.check_identity({"window_id": "w1", "process_name": "Trae.exe", "title": "Agui - TRAE"}, expected)
    with pytest.raises(SafetyError) as wrong_process:
        gate.check_identity({"window_id": "w1", "process_name": "Code.exe", "title": "Agui - TRAE"}, expected)
    assert wrong_process.value.code == "identity_mismatch"
    with pytest.raises(SafetyError) as wrong_title:
        gate.check_identity({"window_id": "w1", "process_name": "Trae.exe", "title": "Agui"}, expected)
    assert wrong_title.value.code == "identity_mismatch"


def test_allow_and_revoke(gate):
    gate.allow("w2")
    gate.check_window("w2")
    gate.revoke("w2")
    with pytest.raises(SafetyError):
        gate.check_window("w2")


# The perception lane reaches the same gate through two further doors — an identity callback instead
# of a compared snapshot, and its own exception categories. Both are honoured by the merged gate,
# so these are kept as that lane wrote them.


def test_unknown_window_blocked(store):
    gate = SafetyGate({"w1"}, approvals=store)
    with pytest.raises(SafetyError) as ei:
        gate.check_action("w2", "trae.chat.send_button", "click", None)
    assert ei.value.code == "window_not_allowed"


def test_normal_action_allowed(store):
    gate = SafetyGate({"w1"}, approvals=store)
    assert gate.check_action("w1", "trae.chat.send_button", "click", None) is None


def test_high_impact_requires_an_approval_category(store):
    gate = SafetyGate({"w1"}, approvals=store)
    with pytest.raises(ApprovalRequired) as ei:
        gate.check_action("w1", "trae.chat.approval_mode", "click", None)
    assert ei.value.code == "approval_required"


def test_high_impact_with_valid_token(store):
    approval = store.create_approval({"semantic_id": "trae.chat.approval_mode", "action": "click"})
    gate = SafetyGate({"w1"}, approvals=store)
    approval_id = gate.check_action("w1", "trae.chat.approval_mode", "click", approval["token"])
    assert approval_id == approval["approval_id"]
    with pytest.raises(ApprovalRequired):
        gate.check_action("w1", "trae.chat.approval_mode", "click", approval["token"])


def test_a_gateless_token_is_not_an_approval(store):
    """A grant that names nothing actionable buys nothing, whichever lane minted it."""
    approval = store.create_approval({"note": "everything"})
    gate = SafetyGate({"w1"}, approvals=store)
    with pytest.raises(ApprovalRequired):
        gate.check_action("w1", "trae.chat.approval_mode", "click", approval["token"])


def test_identity_checker_failure(store):
    def checker(window_id):
        raise RuntimeError("process replaced")

    gate = SafetyGate({"w1"}, approvals=store, identity_checker=checker)
    with pytest.raises(IdentityCheckFailed) as ei:
        gate.check_action("w1", "trae.chat.send_button", "click", None)
    assert ei.value.code == "identity_mismatch"

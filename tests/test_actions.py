import pytest

from semantic.element import GUIElement

SEND = "trae.chat.send_button"
COMPOSER = "trae.chat.composer"
APPROVAL = "trae.chat.approval_mode"


class _CodeError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


class _StubResolver:
    def __init__(self, element=None, exc=None):
        self.element = element
        self.exc = exc
        self.registry = {}

    def resolve(self, window_id, semantic_id):
        if self.exc:
            raise self.exc
        return self.element


def _element(window_id, evidence):
    return GUIElement(id="e1", window_id=window_id, role="button", name="发送", bounds=(0, 0, 1, 1),
                      evidence=evidence)


def test_click_is_verified_by_the_registry_postcondition(plane):
    window = plane.window_id
    plane.executor.perform(window, COMPOSER, "type", {"text": "hello"})
    result = plane.executor.perform(window, SEND, "click", {"text": "hello"})
    assert (result.success, result.verified) == (True, True)
    assert result.before_snapshot_id and result.after_snapshot_id
    assert plane.channel.messages[-1].startswith("USER: hello")


def test_action_without_a_registered_postcondition_reports_success_but_not_verified(plane):
    result = plane.executor.perform(plane.window_id, "trae.chat.model_select", "click")
    assert result.success is True
    assert result.verified is False


def test_only_the_four_documented_actions_are_accepted(plane):
    with pytest.raises(ValueError):
        plane.executor.perform(plane.window_id, SEND, "hover")


def test_missing_locator_is_a_result_not_an_exception(plane):
    result = plane.executor.perform(plane.window_id, "trae.chat.nope", "click")
    assert result.success is False
    assert result.error_code == "locator_missing"


def test_ambiguous_candidates_stop_instead_of_guessing(plane):
    plane.executor.resolver = _StubResolver(exc=_CodeError("conflict", "2 similar candidates"))
    assert plane.executor.perform(plane.window_id, SEND, "click").error_code == "conflict"


def test_channel_failure_is_reported_with_both_snapshots(plane):
    def refuse(window_id, selector):
        raise RuntimeError("renderer gone")

    plane.channel.focus = refuse
    result = plane.executor.perform(plane.window_id, COMPOSER, "type", {"text": "hi"})
    assert result.success is False
    assert result.error_code == "not_submitted"
    assert result.before_snapshot_id and result.after_snapshot_id


def test_element_belonging_to_another_window_fails_the_identity_check(plane):
    plane.executor.resolver = _StubResolver(_element("someone-elses-window", {"cdp_selector": ".x"}))
    assert plane.executor.perform(plane.window_id, SEND, "click").error_code == "identity_mismatch"


def test_resolution_without_a_channel_selector_is_refused(plane):
    plane.executor.resolver = _StubResolver(_element(plane.window_id, {"ocr_box": [0, 0, 1, 1]}))
    assert plane.executor.perform(plane.window_id, SEND, "click").error_code == "locator_missing"


def test_high_impact_action_without_a_token_never_reaches_the_channel(plane):
    before = list(plane.channel.actions)
    result = plane.executor.perform(plane.window_id, APPROVAL, "click")
    assert result.error_code == "approval_required"
    assert plane.channel.actions == before


def test_high_impact_action_succeeds_once_a_human_grants_it(plane, grant_approval):
    plane.executor.perform(plane.window_id, APPROVAL, "click")
    token = grant_approval(plane, APPROVAL, "click")
    result = plane.executor.perform(plane.window_id, APPROVAL, "click", approval_token=token)
    assert (result.success, result.verified) == (True, True)
    assert plane.channel.approval_mode == "manual"


def test_every_attempt_writes_an_audit_row(plane):
    plane.executor.perform(plane.window_id, "trae.chat.nope", "click")
    row = [e for e in plane.store.events(kind="action")][-1]
    assert row["semantic_id"] == "trae.chat.nope"
    assert row["payload"]["success"] is False
    assert row["payload"]["error_code"] == "locator_missing"


def test_snapshots_record_the_elements_they_observed(plane):
    result = plane.executor.perform(plane.window_id, COMPOSER, "type", {"text": "hi"})
    snapshot = plane.store.get_snapshot(result.after_snapshot_id)
    assert snapshot["window_id"] == plane.window_id
    assert ".chat-input-v2-input-box-editable" in {e["selector"] for e in snapshot["elements"]}

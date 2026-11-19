"""Draft Phase 2 integration adapter tests (RoutedExecutor).

Lock the composition of the verified drafts into an executor-shaped surface and
the design 11.4 gaps it closes: #4 approval double-gate (router requires_approval
layered over the frozen semantic_id-keyword gate), #5 principle-6 retry via
decide_retry, #6 four-state preservation through the frozen envelope bridge, plus
principle-3 OCR write exclusion. Injected fakes only — nothing frozen wired."""

import pytest

from packages.execution.routed_executor import RoutedExecutor
from packages.focusguard.outcome import ActionResult, ResultState
from packages.routing.capability import Capability, Channel, InterferenceRisk, OperationImpact
from packages.routing.policy import InterferencePolicy


def _result(state, channel=Channel.APP_PROTOCOL, risk=InterferenceRisk.NONE, verified=True):
    return ActionResult(state=state, channel=channel, risk=risk, effect_verified=verified)


def _cap(operation="invoke", impact=OperationImpact.LOW, idempotent=True, channels=None, risk=None):
    return Capability(
        app="demo", operation=operation,
        channels=channels or {Channel.APP_PROTOCOL: True},
        risk=risk or {Channel.APP_PROTOCOL: InterferenceRisk.NONE},
        impact=impact, idempotent=idempotent,
    )


class ExecSpy:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, channel):
        self.calls.append(channel)
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class ApprovalSpy:
    def __init__(self, approval_id="apr_1", raises=None):
        self.calls = []
        self.approval_id = approval_id
        self.raises = raises

    def __call__(self, semantic_id, action, token):
        self.calls.append((semantic_id, action, token))
        if self.raises:
            raise self.raises
        return self.approval_id


def test_high_impact_none_risk_denied_without_token():
    cap = _cap(impact=OperationImpact.HIGH)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    out = RoutedExecutor(spy).run(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert out.executed is False
    assert out.decision.channel is None
    assert out.decision.requires_approval is True
    assert out.denied_reason == "no_executable_channel"
    assert spy.calls == []


def test_high_impact_none_risk_executes_with_token_and_consumes():
    cap = _cap(impact=OperationImpact.HIGH)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    approval = ApprovalSpy()
    out = RoutedExecutor(spy, approval).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke", approval_token="tok")
    assert out.executed is True
    assert out.approval_id == "apr_1"
    assert approval.calls == [("sid", "invoke", "tok")]
    assert out.envelope.success is True


def test_low_impact_none_risk_needs_no_approval():
    cap = _cap(impact=OperationImpact.LOW)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    approval = ApprovalSpy()
    out = RoutedExecutor(spy, approval).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert out.executed is True
    assert out.decision.requires_approval is False
    assert out.approval_id is None
    assert approval.calls == []


def test_focus_switch_strict_requires_token():
    cap = _cap(channels={Channel.UIA: True}, risk={Channel.UIA: InterferenceRisk.FOCUS_SWITCH})
    spy = ExecSpy([_result(ResultState.SUCCESS_WITH_INTERFERENCE, Channel.UIA, InterferenceRisk.FOCUS_SWITCH)])
    approval = ApprovalSpy()
    denied = RoutedExecutor(spy, approval).run(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert denied.executed is False and denied.decision.channel is None
    out = RoutedExecutor(spy, approval).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke", approval_token="tok")
    assert out.executed is True and out.decision.channel is Channel.UIA
    assert approval.calls == [("sid", "invoke", "tok")]


def test_invalid_token_propagates_and_blocks_execution():
    cap = _cap(impact=OperationImpact.HIGH)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    approval = ApprovalSpy(raises=RuntimeError("bad token"))
    with pytest.raises(RuntimeError):
        RoutedExecutor(spy, approval).run(
            cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke", approval_token="bad")
    assert spy.calls == []


def test_missing_consumer_fails_closed():
    cap = _cap(impact=OperationImpact.HIGH)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    out = RoutedExecutor(spy, consume_approval=None).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke", approval_token="tok")
    assert out.executed is False
    assert out.denied_reason == "approval_required"
    assert spy.calls == []


def test_non_idempotent_unconfirmed_no_auto_retry():
    cap = _cap(idempotent=False)
    spy = ExecSpy([_result(ResultState.UNCONFIRMED, verified=False)])
    out = RoutedExecutor(spy).run(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert len(spy.calls) == 1
    assert out.attempts == 0
    assert out.retry.allow_retry is False
    assert out.retry.requires_approval is True


def test_idempotent_unconfirmed_retries_within_budget_only():
    cap = _cap(idempotent=True)
    spy = ExecSpy([_result(ResultState.UNCONFIRMED, verified=False)])
    out = RoutedExecutor(spy, max_attempts=2).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert len(spy.calls) == 3
    assert out.attempts == 2
    assert out.retry.allow_retry is False
    assert out.retry.requires_approval is True


def test_succeeded_never_retries():
    cap = _cap(idempotent=True)
    spy = ExecSpy([_result(ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED)])
    out = RoutedExecutor(spy).run(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert len(spy.calls) == 1
    assert out.retry.allow_retry is False


def test_unconfirmed_preserved_distinct_from_failed_in_envelope():
    cap = _cap(idempotent=False)
    unconf = RoutedExecutor(ExecSpy([_result(ResultState.UNCONFIRMED, verified=False)])).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    failed = RoutedExecutor(ExecSpy([_result(ResultState.FAILED, verified=False)])).run(
        cap, InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke")
    assert unconf.result.state is ResultState.UNCONFIRMED
    assert unconf.envelope.state is ResultState.UNCONFIRMED
    assert unconf.envelope.success is False and unconf.envelope.error_code is None
    assert failed.envelope.state is ResultState.FAILED
    assert failed.envelope.error_code is not None
    assert unconf.envelope.state is not failed.envelope.state


def test_ocr_excluded_for_write_in_integration():
    cap = _cap(
        operation="invoke",
        channels={Channel.OCR_VISION: True, Channel.UIA: True},
        risk={Channel.OCR_VISION: InterferenceRisk.LOGICAL_ONLY, Channel.UIA: InterferenceRisk.FOCUS_SWITCH},
    )
    spy = ExecSpy([_result(ResultState.SUCCESS_WITH_INTERFERENCE, Channel.UIA, InterferenceRisk.FOCUS_SWITCH)])
    out = RoutedExecutor(spy).run(cap, InterferencePolicy.BALANCED, "sid", "invoke")
    assert out.decision.channel is Channel.UIA
    assert Channel.OCR_VISION not in out.decision.fallbacks
"""Draft measured capability table loads and routes per Phase 1 evidence."""

from packages.routing import (
    Channel,
    InterferencePolicy,
    InterferenceRisk,
    StaticRouter,
    load_capability_table,
)


def _table():
    return load_capability_table()


def test_table_contains_measured_entries():
    table = _table()
    assert ("native-test", "invoke") in table
    assert ("native-test", "set_value") in table
    assert ("native-test", "toggle") in table
    assert ("trae", "send_task") in table
    assert ("wechat", "send_message") in table


def test_native_uia_risk_is_measured_focus_switch():
    cap = _table()[("native-test", "invoke")]
    assert cap.risk_of(Channel.UIA) is InterferenceRisk.FOCUS_SWITCH
    assert cap.risk_of(Channel.FOREGROUND_INPUT) is InterferenceRisk.PHYSICAL_INPUT


def test_native_invoke_balanced_selects_uia():
    cap = _table()[("native-test", "invoke")]
    decision = StaticRouter().route(cap, InterferencePolicy.BALANCED)
    assert decision.channel is Channel.UIA
    assert decision.requires_approval is False


def test_native_invoke_strict_denies_uia_without_approval():
    cap = _table()[("native-test", "invoke")]
    decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is None
    assert decision.requires_approval is True


def test_wechat_negative_returns_reason():
    cap = _table()[("wechat", "send_message")]
    decision = StaticRouter().route(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert decision.channel is None
    assert "wechat" in decision.reason.lower()


def test_selfdrawn_negative_returns_reason():
    cap = _table()[("selfdrawn-test", "invoke")]
    assert cap.supported() == []
    decision = StaticRouter().route(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert decision.channel is None
    assert "self-drawn" in decision.reason.lower()


def test_trae_send_task_measured_none_still_gated_by_approval():
    cap = _table()[("trae", "send_task")]
    assert cap.risk_of(Channel.APP_PROTOCOL) is InterferenceRisk.NONE
    denied = StaticRouter().route(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=False)
    assert denied.channel is None
    allowed = StaticRouter().route(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert allowed.channel is Channel.APP_PROTOCOL


def test_trae_read_interfaces_measured_none_allowed_under_strict():
    for operation in ("get_task_status", "read_task_result"):
        cap = _table()[("trae", operation)]
        assert cap.risk_of(Channel.APP_PROTOCOL) is InterferenceRisk.NONE
        decision = StaticRouter().route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
        assert decision.channel is Channel.APP_PROTOCOL
        assert decision.requires_approval is False
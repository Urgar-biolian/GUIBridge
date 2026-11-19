"""Draft UiaPatternChannel unit tests (fakes; no live window, no frozen wiring)."""

from __future__ import annotations

import time

from packages.execution.uia_channel import UiaPatternChannel
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.routing.capability import Channel, InterferenceRisk


def _snap(hwnd: int = 1) -> FocusSnapshot:
    return FocusSnapshot(foreground_hwnd=hwnd, cursor_xy=(0, 0), target_active=True, ts=time.time())


class FakePattern:
    def __init__(self, state: dict, action: str, *, mutate: bool = True, raises: bool = False):
        self.state = state
        self.action = action
        self.mutate = mutate
        self.raises = raises

    def _apply(self):
        if self.raises:
            raise RuntimeError("pattern call failed")
        if not self.mutate:
            return
        if self.action == "invoke":
            self.state["clicked"] += 1
        elif self.action == "toggle":
            self.state["toggle"] = 1 - self.state["toggle"]

    def Invoke(self):
        self._apply()

    def Toggle(self):
        self._apply()

    def SetValue(self, value):
        if self.raises:
            raise RuntimeError("pattern call failed")
        if self.mutate:
            self.state["value"] = value


class FakeControl:
    def __init__(self, patterns: dict):
        self.patterns = patterns


class FakeGuard:
    def __init__(self, *, interference: bool = False, displacement: int = 0):
        self.interference = interference
        self.displacement = displacement

    def snapshot(self):
        return _snap()

    def wrap_with_events(self, action):
        before = self.snapshot()
        action()  # propagate exceptions like the real guard
        after = self.snapshot()
        events = [(time.time(), 99)] if self.interference else []
        return FocusRun(
            result=None, before=before, after=after,
            foreground_events=events,
            unexpected_focus_switch=self.interference,
            cursor_displacement=self.displacement,
            external_input_during_window=False,
            hook_foreground_events=events,
            event_hook_active=True,
        )


def _verify(action, before, after, args):
    if action == "invoke":
        return after["clicked"] > before["clicked"]
    if action == "set_value":
        return after["value"] == args["value"]
    if action == "toggle":
        return after["toggle"] != before["toggle"]
    return False


def make_channel(*, interference=False, displacement=0, mutate=True, raises=False,
                 control_present=True, pattern_present=True):
    state = {"clicked": 0, "value": "", "toggle": 0}

    def resolve(window_id, semantic_id):
        if not control_present:
            return None
        patterns = {}
        for act in ("invoke", "set_value", "toggle"):
            if pattern_present:
                patterns[act] = FakePattern(state, act, mutate=mutate, raises=raises)
        return FakeControl(patterns)

    def pattern_of(control, action):
        return control.patterns.get(action)

    def read_state(window_id, semantic_id):
        return dict(state)

    guard = FakeGuard(interference=interference, displacement=displacement)
    channel = UiaPatternChannel(
        resolve=resolve, pattern_of=pattern_of, guard_for=lambda wid: guard,
        read_state=read_state, verify=_verify,
    )
    return channel, state


def test_invoke_verified_with_focus_switch():
    channel, _ = make_channel(interference=True)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.SUCCESS_WITH_INTERFERENCE
    assert result.risk is InterferenceRisk.FOCUS_SWITCH
    assert result.channel is Channel.UIA
    assert result.effect_verified is True
    assert result.unexpected_focus_switch is True


def test_invoke_verified_no_interference():
    channel, _ = make_channel(interference=False)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    assert result.effect_verified is True


def test_invoke_pattern_unavailable_is_failed():
    channel, _ = make_channel(pattern_present=False)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.FAILED
    assert result.effect_verified is False
    assert "invoke pattern unavailable" in result.evidence["error"]


def test_missing_control_is_failed():
    channel, _ = make_channel(control_present=False)
    result = channel.toggle("w", "chk")
    assert result.state is ResultState.FAILED
    assert "toggle pattern unavailable" in result.evidence["error"]


def test_invoke_executed_but_unverified_is_unconfirmed():
    channel, _ = make_channel(mutate=False)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.UNCONFIRMED
    assert result.effect_verified is False
    assert "error" not in result.evidence


def test_set_value_verified():
    channel, _ = make_channel()
    result = channel.set_value("w", "edit", "hello")
    assert result.effect_verified is True
    assert result.state in (ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
                            ResultState.SUCCESS_WITH_INTERFERENCE)
    assert result.evidence["value"] == "hello"


def test_set_value_mismatch_is_unconfirmed():
    channel, _ = make_channel(mutate=False)
    result = channel.set_value("w", "edit", "hello")
    assert result.state is ResultState.UNCONFIRMED
    assert result.effect_verified is False


def test_toggle_verified():
    channel, state = make_channel()
    result = channel.toggle("w", "chk")
    assert result.effect_verified is True
    assert state["toggle"] == 1


def test_action_raises_is_failed():
    channel, _ = make_channel(raises=True)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.FAILED
    assert "pattern call failed" in result.evidence["error"]


def test_read_state_delegates():
    channel, state = make_channel()
    state["value"] = "preset"
    assert channel.read_state("w", "edit")["value"] == "preset"


def test_evidence_carries_focus_signals():
    channel, _ = make_channel(interference=True, displacement=7)
    result = channel.invoke("w", "btn")
    assert result.evidence["cursor_displacement"] == 7
    assert result.evidence["foreground_events"] == [99]
    assert result.evidence["event_hook_active"] is True
    assert result.evidence["external_input_during_window"] is False


def test_cursor_displacement_alone_marks_interference():
    channel, _ = make_channel(interference=False, displacement=5)
    result = channel.invoke("w", "btn")
    assert result.state is ResultState.SUCCESS_WITH_INTERFERENCE
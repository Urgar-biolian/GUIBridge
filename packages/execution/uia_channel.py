"""UIA pattern execution channel (Phase 0 draft, pending B-line approval).

Never falls back to SendInput; foreground input stays a separate channel.
The concrete UiaPatternChannel below is a DRAFT implementation: it is not wired
into the frozen engine/mcp_gateway and makes no old-contract change. Target-
specific parts (control resolution, pattern access, state readback, effect
verification) are injected so the channel stays testable without a live window;
the measured native UIA risk is FOCUS_SWITCH (E1b/E1c), not LOGICAL_ONLY.
"""

from __future__ import annotations

from typing import Protocol

from packages.focusguard.classify import classify
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import ActionResult
from packages.routing.capability import Channel, InterferenceRisk


class UIAExecChannel(Protocol):
    def invoke(self, window_id: str, semantic_id: str) -> ActionResult: ...

    def set_value(self, window_id: str, semantic_id: str, value: str) -> ActionResult: ...

    def toggle(self, window_id: str, semantic_id: str) -> ActionResult: ...

    def read_state(self, window_id: str, semantic_id: str) -> dict: ...


class UiaPatternChannel:
    """Draft UIA channel: guard-wrapped pattern call + readback + four-state classify.

    Injected callables:
      resolve(window_id, semantic_id) -> control | None
      pattern_of(control, action) -> pattern | None  (action: invoke/set_value/toggle)
      guard_for(window_id) -> guard with wrap_with_events(action)->FocusRun, snapshot()
      read_state(window_id, semantic_id) -> state
      verify(action, before, after, args) -> bool
    """

    def __init__(self, resolve, pattern_of, guard_for, read_state, verify,
                 channel: Channel = Channel.UIA) -> None:
        self.resolve = resolve
        self.pattern_of = pattern_of
        self.guard_for = guard_for
        self._read_state = read_state
        self.verify = verify
        self.channel = channel

    def invoke(self, window_id: str, semantic_id: str) -> ActionResult:
        return self._perform("invoke", window_id, semantic_id, {})

    def set_value(self, window_id: str, semantic_id: str, value: str) -> ActionResult:
        return self._perform("set_value", window_id, semantic_id, {"value": value})

    def toggle(self, window_id: str, semantic_id: str) -> ActionResult:
        return self._perform("toggle", window_id, semantic_id, {})

    def read_state(self, window_id: str, semantic_id: str) -> dict:
        return self._read_state(window_id, semantic_id)

    def _perform(self, action: str, window_id: str, semantic_id: str, args: dict) -> ActionResult:
        control = self.resolve(window_id, semantic_id)
        pattern = self.pattern_of(control, action) if control is not None else None
        before = self._read_state(window_id, semantic_id)
        guard = self.guard_for(window_id)
        if pattern is None:
            run = FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot())
            return self._result(run, False, {"state_before": before},
                                error=f"{action} pattern unavailable")

        def call() -> None:
            if action == "invoke":
                pattern.Invoke()
            elif action == "set_value":
                pattern.SetValue(args["value"])
            elif action == "toggle":
                pattern.Toggle()

        try:
            run = guard.wrap_with_events(call)
            error = None
        except Exception as exc:  # confirmed pattern/COM error -> FAILED
            run = FocusRun(result=None, before=guard.snapshot(), after=guard.snapshot())
            error = repr(exc)
        after = self._read_state(window_id, semantic_id)
        verified = bool(self.verify(action, before, after, args)) if error is None else False
        evidence = {"state_before": before, "state_after": after, **args}
        return self._result(run, verified, evidence, error)

    def _result(self, run: FocusRun, verified: bool, evidence: dict,
                error: str | None = None) -> ActionResult:
        state = classify(run, verified, error, self.channel)
        evidence = dict(evidence)
        evidence["cursor_displacement"] = run.cursor_displacement
        evidence["foreground_events"] = [fg for _, fg in run.foreground_events]
        evidence["external_input_during_window"] = run.external_input_during_window
        evidence["hook_foreground_events"] = [fg for _, fg in run.hook_foreground_events]
        evidence["event_hook_active"] = run.event_hook_active
        if error:
            evidence["error"] = error
        return ActionResult(
            state=state,
            channel=self.channel,
            # Measured native UIA risk is FOCUS_SWITCH (E1b/E1c), not LOGICAL_ONLY.
            risk=InterferenceRisk.FOCUS_SWITCH,
            effect_verified=verified,
            evidence=evidence,
            focus_before=run.before,
            focus_after=run.after,
            unexpected_focus_switch=run.unexpected_focus_switch,
        )

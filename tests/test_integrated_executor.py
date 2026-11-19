"""G1 integration layer: routed + guarded + four-state + audited, end to end.

Uses the REAL measured capability table, REAL FocusRun dataclass, REAL EventStore
(tmp sqlite); only the Win32 guard is faked (its interference metrics are injected),
since the real guard's measurement is already grounded in the live probes."""

import pytest

from events.store import EventStore
from packages.execution.integrated import IntegratedExecutor
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.routing import Channel, InterferencePolicy, load_capability_table


def _snap(ts):
    return FocusSnapshot(foreground_hwnd=100, cursor_xy=(0, 0), target_active=True, ts=ts)


class FakeGuard:
    def __init__(self, cursor=0, switch=False):
        self.cursor = cursor
        self.switch = switch
        self.calls = 0

    def wrap_with_events(self, fn):
        self.calls += 1
        return FocusRun(result=fn(), before=_snap(1.0), after=_snap(2.0),
                        cursor_displacement=self.cursor, unexpected_focus_switch=self.switch)


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "int.db"))
    # What `GUIBridgeEngine.list_windows` does on a real desktop: the window is enumerated into
    # the identity table before anything may write evidence about it (snapshots are FK-bound).
    # "native" is the window the UIA-only interference cases write under.
    s.register_window("trae", "Trae.exe", "Agui - TRAE", {})
    s.register_window("native", "Trae.exe", "Agui - TRAE", {})
    yield s
    s.close()


@pytest.fixture(scope="module")
def table():
    return load_capability_table()


def _consume(sid, act, tok):
    return "apr_1"


def test_low_impact_clean_success_persists_evidence(store, table):
    guard = FakeGuard()
    ex = IntegratedExecutor(guard, store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "get_task_status")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke",
                          lambda ch: (True, None))
    assert outcome.executed is True
    assert outcome.decision.channel is Channel.APP_PROTOCOL
    assert env.state is ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
    assert env.success is True and env.verified is True
    assert len(env.evidence) == 2
    assert guard.calls == 1


def test_high_impact_denied_without_token(store, table):
    guard = FakeGuard()
    ex = IntegratedExecutor(guard, store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "send_task")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke",
                          lambda ch: (True, None))
    assert outcome.executed is False
    assert outcome.denied_reason == "no_executable_channel"
    assert env is None
    assert guard.calls == 0


def test_high_impact_executes_with_token_and_consumes(store, table):
    ex = IntegratedExecutor(FakeGuard(), store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "send_task")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke",
                          lambda ch: (True, None), approval_token="tok")
    assert outcome.executed is True
    assert outcome.approval_id == "apr_1"
    assert env.success is True


def test_unconfirmed_non_idempotent_no_auto_retry(store, table):
    guard = FakeGuard()
    ex = IntegratedExecutor(guard, store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "send_task")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke",
                          lambda ch: (False, None), approval_token="tok")
    assert env.state is ResultState.UNCONFIRMED
    assert env.success is False and env.error_code is None
    assert outcome.retry.allow_retry is False
    assert outcome.attempts == 0
    assert guard.calls == 1


def test_focus_switch_classified_success_with_interference(store, table):
    ex = IntegratedExecutor(FakeGuard(switch=True), store, "native", _consume)
    outcome, env = ex.run(table[("native-test", "invoke")],
                          InterferencePolicy.FOREGROUND_ALLOWED, "sid", "invoke",
                          lambda ch: (True, None), approval_token="tok")
    assert env.state is ResultState.SUCCESS_WITH_INTERFERENCE
    assert env.interference_observed is True


def test_confirmed_error_is_failed(store, table):
    ex = IntegratedExecutor(FakeGuard(), store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "get_task_status")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke",
                          lambda ch: (False, "boom"))
    assert env.state is ResultState.FAILED
    assert env.error_code == "boom"
    assert env.success is False


def test_backend_exception_is_failed_not_unconfirmed(store, table):
    def boom(ch):
        raise RuntimeError("backend down")
    ex = IntegratedExecutor(FakeGuard(), store, "trae", _consume)
    outcome, env = ex.run(table[("trae", "get_task_status")],
                          InterferencePolicy.STRICT_NO_INTERFERENCE, "sid", "invoke", boom)
    assert env.state is ResultState.FAILED
    assert env.error_code == "exec_error"
    assert env.success is False
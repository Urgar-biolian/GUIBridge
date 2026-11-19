"""Draft candidate for R3 option (a): external-input effect attribution.

Pending B-line approval (R3). classify() reports verified=True as SUCCESS_*
without considering whether external input polluted the observation window. For
channels that do NOT inject physical input themselves (UIA, APP_PROTOCOL,
OFFICIAL_API, CLI, VM_ISOLATED, OCR_VISION), external_input_during_window=True
means input arrived from outside during the window, so a verified effect cannot
be confidently attributed to our action -> downgrade to UNCONFIRMED (principle 6).

FOREGROUND_INPUT is excluded: it injects input itself and GetLastInputInfo cannot
separate self-injection from external input (design open question 5), so the flag
is expected True there and must not trigger a downgrade. Separating self-injection
needs an explicit marker mechanism, not implemented here.

external_input_during_window=None means the measurement was unavailable: a
measurement gap, not evidence of pollution, so it does not downgrade. Whether
"unknown" should also downgrade is left to B (R3).

This module does NOT replace classify() and wires into nothing frozen.
"""

from __future__ import annotations

from packages.routing.capability import Channel

from .classify import classify
from .monitor import FocusRun
from .outcome import ResultState

_SUCCEEDED = (
    ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
    ResultState.SUCCESS_WITH_INTERFERENCE,
)
_SELF_INPUT_CHANNELS = frozenset({Channel.FOREGROUND_INPUT})


def classify_with_attribution(
    run: FocusRun,
    verified: bool,
    error: str | None,
    channel: Channel,
) -> ResultState:
    state = classify(run, verified, error, channel)
    if state not in _SUCCEEDED:
        return state
    if channel in _SELF_INPUT_CHANNELS:
        return state
    if run.external_input_during_window is True:
        return ResultState.UNCONFIRMED
    return state
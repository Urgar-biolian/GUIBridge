"""Four-state classification shared by probe channels (draft, pending B approval)."""

from __future__ import annotations

from packages.routing.capability import Channel

from .monitor import FocusRun
from .outcome import ResultState


def classify(
    run: FocusRun,
    verified: bool,
    error: str | None,
    channel: Channel,
) -> ResultState:
    if error or not verified:
        return ResultState.FAILED
    if channel is Channel.FOREGROUND_INPUT:
        return ResultState.SUCCESS_WITH_INTERFERENCE
    if run.unexpected_focus_switch or run.cursor_displacement > 0:
        return ResultState.SUCCESS_WITH_INTERFERENCE
    return ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
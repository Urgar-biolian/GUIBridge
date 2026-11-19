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
    """FAILED needs a confirmed error; lacking positive confirmation of success
    without an error is UNCONFIRMED, not a claimed definite failure (principle 6
    distinguishes the two for non-idempotent retry)."""
    if error:
        return ResultState.FAILED
    if not verified:
        return ResultState.UNCONFIRMED
    if channel is Channel.FOREGROUND_INPUT:
        return ResultState.SUCCESS_WITH_INTERFERENCE
    if run.unexpected_focus_switch or run.cursor_displacement > 0:
        return ResultState.SUCCESS_WITH_INTERFERENCE
    return ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED
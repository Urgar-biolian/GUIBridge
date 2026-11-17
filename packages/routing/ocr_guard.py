"""Draft candidate for R6 option (a): enforce principle 3 at routing selection.

Pending B-line approval (R6). StaticRouter ranks OCR_VISION as a selectable
execution channel; if a capability declared it supported with a non-unknown risk
for a write operation, the router could select OCR to execute a write — violating
"OCR locate-only, not background input" (design channel table: OCR_VISION 仅定位).
This candidate excludes OCR_VISION from execution selection for write operations
while leaving read/locate operations free to use OCR (NONE risk). It does NOT
replace StaticRouter and wires into nothing frozen; R6 option (b) would instead
rely solely on the capability-table data discipline.
"""

from __future__ import annotations

from dataclasses import replace

from .capability import WRITE_OPERATIONS, Capability, Channel
from .policy import InterferencePolicy
from .router import ChannelDecision, StaticRouter


def is_write_operation(operation: str) -> bool:
    return operation in WRITE_OPERATIONS


def route_ocr_aware(
    capability: Capability,
    policy: InterferencePolicy,
    approved: bool = False,
    router: StaticRouter | None = None,
) -> ChannelDecision:
    router = router or StaticRouter()
    if is_write_operation(capability.operation) and Channel.OCR_VISION in capability.supported():
        channels = {
            channel: ok
            for channel, ok in capability.channels.items()
            if channel is not Channel.OCR_VISION
        }
        capability = replace(capability, channels=channels)
    return router.route(capability, policy, approved)
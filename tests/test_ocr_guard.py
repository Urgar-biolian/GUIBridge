"""Draft OCR-aware routing tests (R6 option a, design channel table principle 3).

Locks the candidate: OCR_VISION is excluded from execution selection for write
operations (the unguarded StaticRouter would otherwise pick a low-risk OCR entry
to execute a write), while read/locate operations may still use OCR. Draft
pending B-line approval; StaticRouter is not replaced and nothing frozen wired."""

from packages.routing import (
    Capability,
    Channel,
    InterferencePolicy,
    InterferenceRisk,
    StaticRouter,
)
from packages.routing.capability import WRITE_OPERATIONS
from packages.routing.ocr_guard import is_write_operation, route_ocr_aware


def _cap(operation, channels, risk):
    return Capability(app="demo", operation=operation, channels=channels, risk=risk)


def test_unguarded_router_would_select_ocr_for_write():
    cap = _cap(
        "invoke",
        {Channel.OCR_VISION: True, Channel.UIA: True},
        {Channel.OCR_VISION: InterferenceRisk.LOGICAL_ONLY, Channel.UIA: InterferenceRisk.FOCUS_SWITCH},
    )
    decision = StaticRouter().route(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert decision.channel is Channel.OCR_VISION  # the principle-3 gap R6 addresses


def test_ocr_aware_excludes_ocr_for_write():
    cap = _cap(
        "invoke",
        {Channel.OCR_VISION: True, Channel.UIA: True},
        {Channel.OCR_VISION: InterferenceRisk.LOGICAL_ONLY, Channel.UIA: InterferenceRisk.FOCUS_SWITCH},
    )
    decision = route_ocr_aware(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert decision.channel is Channel.UIA


def test_ocr_only_write_is_rejected():
    cap = _cap("send_message", {Channel.OCR_VISION: True},
               {Channel.OCR_VISION: InterferenceRisk.LOGICAL_ONLY})
    decision = route_ocr_aware(cap, InterferencePolicy.FOREGROUND_ALLOWED, approved=True)
    assert decision.channel is None


def test_read_operation_keeps_ocr():
    cap = _cap("get_task_status", {Channel.OCR_VISION: True},
               {Channel.OCR_VISION: InterferenceRisk.NONE})
    decision = route_ocr_aware(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.OCR_VISION


def test_read_operation_ocr_available_as_fallback():
    cap = _cap(
        "read_task_result",
        {Channel.OCR_VISION: True, Channel.APP_PROTOCOL: True},
        {Channel.OCR_VISION: InterferenceRisk.NONE, Channel.APP_PROTOCOL: InterferenceRisk.NONE},
    )
    decision = route_ocr_aware(cap, InterferencePolicy.STRICT_NO_INTERFERENCE)
    assert decision.channel is Channel.APP_PROTOCOL
    assert Channel.OCR_VISION in decision.fallbacks


def test_non_ocr_write_unaffected():
    cap = _cap("toggle", {Channel.UIA: True}, {Channel.UIA: InterferenceRisk.FOCUS_SWITCH})
    decision = route_ocr_aware(cap, InterferencePolicy.BALANCED)
    assert decision.channel is Channel.UIA


def test_is_write_operation():
    for op in WRITE_OPERATIONS:
        assert is_write_operation(op) is True
    for op in ("get_task_status", "read_task_result"):
        assert is_write_operation(op) is False
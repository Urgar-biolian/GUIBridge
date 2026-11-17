"""Restricted action execution: relocate -> identity check -> snapshot -> act -> snapshot -> verify."""

from semantic.element import ActionResult


class ActionExecutor:
    def perform(self, window_id: str, semantic_id: str, action: str, args: dict | None = None,
                approval_token: str | None = None) -> ActionResult:
        raise NotImplementedError("S2")
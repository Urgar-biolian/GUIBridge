"""Restricted action execution: safety -> relocate -> snapshot -> act -> snapshot -> verify."""

from __future__ import annotations

import asyncio
import inspect

from execution.safety import SafetyGate, SafetyError
from semantic.element import ActionResult
from semantic.resolver import ResolveError

ALLOWED_ACTIONS = {"click", "type", "select", "invoke"}


class ActionError(RuntimeError):
    code = "conflict"


class ActionExecutor:
    def __init__(self, resolver, safety: SafetyGate, store,
                 snapshotter=None, actor=None, verifier=None):
        """actor(window_id, element, action, args) -> bool; snapshotter(window_id) -> dict."""
        self.resolver = resolver
        self.safety = safety
        self.store = store
        self.snapshotter = snapshotter
        self.actor = actor
        self.verifier = verifier

    async def _maybe_await(self, value):
        return await value if inspect.isawaitable(value) else value

    async def perform_async(self, window_id: str, semantic_id: str, action: str,
                            args: dict | None = None, approval_token: str | None = None) -> ActionResult:
        args = args or {}
        if action not in ALLOWED_ACTIONS:
            raise ActionError(f"unsupported action: {action}")

        approval_id = None
        before_id = ""
        if self.snapshotter:
            before_id = await self._snapshot(window_id, "before")
        try:
            approval_id = self.safety.check_action(window_id, semantic_id, action, approval_token)
            element = await self.resolver.resolve(window_id, semantic_id)
            if self.actor is None:
                raise ActionError("action backend not configured")
            ok = bool(await self._maybe_await(self.actor(window_id, element, action, args)))
        except (SafetyError, ResolveError, ActionError) as e:
            evidence = [before_id] if before_id else []
            self.store.record("action_failed", {
                "semantic_id": semantic_id, "action": action, "error_code": e.code,
                "message": str(e),
            }, evidence=evidence, window_id=window_id, semantic_id=semantic_id, action=action,
                approval_id=approval_id)
            return ActionResult(success=False, verified=False, before_snapshot_id=before_id,
                                after_snapshot_id="", error_code=e.code, evidence=evidence)

        after_id = await self._snapshot(window_id, "after") if self.snapshotter else ""
        verified = False
        if ok and self.verifier is not None:
            verified = bool(await self._maybe_await(
                self.verifier(window_id, semantic_id, action, args, element)))
        evidence = [x for x in (before_id, after_id) if x]
        self.store.record("action", {
            "semantic_id": semantic_id, "action": action, "args": args,
            "success": ok, "verified": verified,
            "bounds": list(element.bounds), "role": element.role, "name": element.name,
            "confidence": element.confidence, "calibrated": False,
        }, evidence=evidence, window_id=window_id, semantic_id=semantic_id, action=action,
            approval_id=approval_id)
        return ActionResult(success=ok, verified=verified, before_snapshot_id=before_id,
                            after_snapshot_id=after_id, error_code=None, evidence=evidence)

    def perform(self, window_id: str, semantic_id: str, action: str,
                args: dict | None = None, approval_token: str | None = None) -> ActionResult:
        return asyncio.run(self.perform_async(window_id, semantic_id, action, args, approval_token))

    async def _snapshot(self, window_id: str, label: str) -> str:
        data = await self._maybe_await(self.snapshotter(window_id)) or {}
        return self.store.add_snapshot(window_id, {"label": label, **data},
                                       image_path=data.get("image_path"))

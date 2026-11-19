"""Restricted action execution: relocate -> identity check -> gate -> snapshot -> act -> snapshot -> verify.

Merged surface. One pipeline serves both lanes: the control plane calls `perform(...)` and gets a
plain `ActionResult` back; the perception lane awaits `perform_async(...)` and gets the same object
after its channel, resolver, actor and verifier have had their awaits resolved. The order is the
control plane's — resolve, re-verify the window, then spend the approval token — so a token is never
consumed for a window we did not confirm.
"""

from __future__ import annotations

import asyncio
import inspect

from execution.safety import SafetyError
from semantic.element import ActionResult

ACTIONS = ("click", "type", "select", "invoke")
ALLOWED_ACTIONS = set(ACTIONS)


class ActionError(ValueError):
    """Refused request or a missing backend.

    Subclasses ValueError because the frozen contract treats an unsupported action name as a
    programming error the caller can also catch as ValueError; `code` carries it into the envelope.
    """

    code = "conflict"

    def __init__(self, code: str, message: str | None = None):
        if message is None:
            code, message = self.code, code
        super().__init__(message)
        self.code = code
        self.message = message


def _error_code(exc: Exception, default: str = "locator_missing") -> str:
    return getattr(exc, "code", default)


def _element_count(summary) -> int:
    """How many controls a stored snapshot summary describes, in either lane's shape."""
    if isinstance(summary, list):
        return len(summary)
    if not isinstance(summary, dict):
        return 0
    for key in ("count", "elements", "elements_summary", "summary"):
        value = summary.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return 0


class ActionExecutor:
    def __init__(self, resolver, channel=None, safety=None, store=None, snapshots=None, verifiers=None,
                 actor=None, snapshotter=None, verifier=None):
        """`actor(window_id, element, action, args)` and `snapshotter(window_id)` are the optional
        backends the perception lane injects; `channel` and `snapshots` are the control plane's."""
        if hasattr(channel, "check_action"):
            # The perception lane calls this positionally as (resolver, safety, store, ...).
            channel, safety, store = None, channel, safety
        self.resolver = resolver
        self.channel = channel
        self.safety = safety
        self.store = store
        self.snapshots = snapshots
        self.snapshotter = snapshotter
        self.verifiers = dict(verifiers or {})
        self.verifier = verifier
        self.actor = actor

    async def _resolve(self, window_id: str, semantic_id: str):
        found = self.resolver.resolve(window_id, semantic_id)
        return await found if inspect.isawaitable(found) else found

    async def _await(self, value):
        return await value if inspect.isawaitable(value) else value

    async def _perform(self, window_id: str, semantic_id: str, action: str, args: dict | None,
                       approval_token: str | None, verification: str | None) -> ActionResult:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action {action!r}; expected one of {', '.join(ACTIONS)}")
        args = args or {}
        try:
            element = await self._resolve(window_id, semantic_id)
        except Exception as exc:
            return self._failed(action, semantic_id, _error_code(exc), str(exc), window_id)

        try:
            await self._check_identity(window_id, element)
            approval_id = self.safety.check_action(window_id, semantic_id, action, approval_token)
        except SafetyError as exc:
            return self._failed(action, semantic_id, exc.code, exc.message, window_id)

        selector = element.evidence.get("cdp_selector") or element.evidence.get("selector")
        if self.actor is None and not selector:
            return self._failed(action, semantic_id, "locator_missing",
                                f"{semantic_id} resolved without a channel selector", window_id)

        before = await self._snapshot(window_id, "before")
        try:
            ok = await self._act(window_id, element, selector, action, args)
        except Exception as exc:
            after = await self._snapshot(window_id, "after")
            code = _error_code(exc, "not_submitted")
            evidence = [e for e in (before, after) if e]
            self._record(action, semantic_id, window_id, False, False, code, str(exc), evidence,
                         approval_id, element, args)
            return ActionResult(success=False, verified=False, error_code=code, before_snapshot_id=before,
                                after_snapshot_id=after, evidence=evidence)

        after = await self._snapshot(window_id, "after")
        verified = await self._verify(window_id, element, selector, semantic_id, action, args,
                                      verification) if ok else False
        evidence = [e for e in (before, after) if e]
        code = None if ok else "not_submitted"
        self._record(action, semantic_id, window_id, ok, verified, code,
                     None if ok else "action backend refused", evidence, approval_id, element, args)
        return ActionResult(success=ok, verified=verified, before_snapshot_id=before,
                            after_snapshot_id=after, error_code=code, evidence=evidence)

    async def _check_identity(self, window_id: str, element) -> None:
        """Re-verify the target before acting: never act on a window we did not choose."""
        if self.channel is None:
            return
        observed = await self._await(self.channel.window_identity(window_id))
        if observed.get("window_id") != element.window_id:
            raise SafetyError("identity_mismatch", f"element belongs to {element.window_id}")
        self.safety.check_identity(observed, {"window_id": window_id,
                                             "process_name": element.evidence.get("process_name")})

    async def _act(self, window_id: str, element, selector: str | None, action: str, args: dict) -> bool:
        if self.actor is not None:
            return bool(await self._await(self.actor(window_id, element, action, args)))
        if action in ("click", "invoke"):
            await self._await(self.channel.click(window_id, selector))
        elif action == "type":
            await self._await(self.channel.focus(window_id, selector))
            await self._await(self.channel.insert_text(window_id, str(args.get("text", ""))))
        elif action == "select":
            await self._await(self.channel.select(window_id, selector, str(args.get("value", ""))))
        return True

    async def _verify(self, window_id: str, element, selector: str | None, semantic_id: str, action: str,
                      args: dict, verification: str | None) -> bool:
        if self.verifier is not None:
            return bool(await self._await(self.verifier(window_id, semantic_id, action, args, element)))
        predicate = self.verifiers.get(verification or self._verification_for(semantic_id))
        if predicate is None:
            return False
        return bool(await self._await(predicate(window_id, selector, args)))

    def _verification_for(self, semantic_id: str) -> str:
        locator = getattr(self.resolver, "registry", {}).get(semantic_id)
        return getattr(locator, "verification", "")

    async def _snapshot(self, window_id: str, label: str) -> str:
        """Return the id of a stored snapshot.

        The control plane's snapshotter persists the row itself and hands back its id; the
        perception lane's snapshotter only describes the window, so the summary is stored here.
        """
        if self.store is None:
            return ""
        if self.snapshots is not None:
            data = await self._await(self.snapshots.capture(window_id)) or {}
            if data.get("snapshot_id"):
                return data["snapshot_id"]
            summary, image_path = data.get("elements", []), data.get("image_path")
        elif self.snapshotter is not None:
            data = await self._await(self.snapshotter(window_id)) or {}
            summary = data.get("elements_summary") or data.get("summary") or data
            image_path = data.get("image_path")
        else:
            return ""
        return self.store.add_snapshot(window_id, summary, image_path=image_path)

    def perform(self, window_id: str, semantic_id: str, action: str, args: dict | None = None,
                approval_token: str | None = None, verification: str | None = None) -> ActionResult:
        """Synchronous entry point. A test or tool that needs the same pipeline on a live event loop
        awaits `perform_async` instead; nesting two loops here would be a caller bug, not a fallback."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.perform_async(window_id, semantic_id, action, args,
                                                  approval_token, verification))
        raise RuntimeError("ActionExecutor.perform() cannot run inside an active event loop; "
                           "await ActionExecutor.perform_async(...) from within it")

    async def perform_async(self, window_id: str, semantic_id: str, action: str,
                            args: dict | None = None, approval_token: str | None = None,
                            verification: str | None = None) -> ActionResult:
        return await self._perform(window_id, semantic_id, action, args, approval_token, verification)

    def _failed(self, action: str, semantic_id: str, code: str, message: str,
                window_id: str | None = None) -> ActionResult:
        self._record(action, semantic_id, window_id, False, False, code, message, [], None, None, None)
        return ActionResult(success=False, verified=False, error_code=code, before_snapshot_id="",
                            after_snapshot_id="")

    def _record(self, action, semantic_id, window_id, success, verified, code, message, evidence,
                approval_id, element=None, args=None) -> None:
        if self.store is None:
            return
        payload = {"semantic_id": semantic_id, "action": action, "success": success, "verified": verified,
                   "error_code": code, "message": message, "snapshots": self._evidence_detail(evidence)}
        if args is not None:
            payload["args"] = args
        if element is not None:
            payload.update({"role": element.role, "name": element.name, "bounds": list(element.bounds),
                            "confidence": getattr(element, "confidence", 0.0),
                            "calibrated": bool(getattr(element, "calibrated", False))})
        self.store.record("action", payload, evidence_paths=evidence, window_id=window_id,
                          semantic_id=semantic_id, action=action, approval_id=approval_id)

    def _evidence_detail(self, snapshot_ids: list[str]) -> list[dict]:
        """What the before/after snapshots contained, copied into the event itself.

        `docs/api.md` freezes the REST surface without a read-by-id snapshot endpoint, so a replay
        client would otherwise hold opaque ids; sql.md makes snapshots append-only, which is what makes
        copying this summary into the audit event safe.
        """
        if self.store is None:
            return []
        detail = []
        for snapshot_id in snapshot_ids:
            row = self.store.get_snapshot(snapshot_id) if snapshot_id else None
            if row is None:
                continue
            detail.append({"snapshot_id": snapshot_id, "ts": row["ts"], "image_path": row["image_path"],
                           "element_count": _element_count(row["elements"])})
        return detail

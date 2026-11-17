"""Restricted action execution: relocate -> identity check -> snapshot -> act -> snapshot -> verify."""

from semantic.element import ActionResult
from execution.safety import SafetyError

ACTIONS = ("click", "type", "select", "invoke")


def _error_code(exc: Exception, default: str = "locator_missing") -> str:
    return getattr(exc, "code", default)


class ActionExecutor:
    def __init__(self, resolver, channel, safety, store=None, snapshots=None, verifiers=None):
        self.resolver = resolver
        self.channel = channel
        self.safety = safety
        self.store = store
        self.snapshots = snapshots
        self.verifiers = dict(verifiers or {})

    def _snapshot(self, window_id: str) -> str:
        if self.snapshots is None:
            return ""
        return self.snapshots.capture(window_id)["snapshot_id"]

    def perform(self, window_id: str, semantic_id: str, action: str, args: dict | None = None,
                approval_token: str | None = None, verification: str | None = None) -> ActionResult:
        if action not in ACTIONS:
            raise ValueError(f"unsupported action {action!r}; expected one of {', '.join(ACTIONS)}")
        args = args or {}
        try:
            element = self.resolver.resolve(window_id, semantic_id)
        except Exception as exc:
            return self._failed(action, semantic_id, _error_code(exc), str(exc), window_id)

        try:
            observed = self.channel.window_identity(window_id)
            if observed.get("window_id") != element.window_id:
                raise SafetyError("identity_mismatch", f"element belongs to {element.window_id}")
            self.safety.check_identity(observed, {"window_id": window_id,
                                                 "process_name": element.evidence.get("process_name")})
            approval_id = self.safety.check_action(window_id, semantic_id, action, approval_token)
        except SafetyError as exc:
            return self._failed(action, semantic_id, exc.code, exc.message, window_id)

        selector = element.evidence.get("cdp_selector") or element.evidence.get("selector")
        if not selector:
            return self._failed(action, semantic_id, "locator_missing",
                                f"{semantic_id} resolved without a channel selector", window_id)

        before = self._snapshot(window_id)
        try:
            self._act(window_id, action, selector, args)
        except Exception as exc:
            after = self._snapshot(window_id)
            code = _error_code(exc, "not_submitted")
            self._record(action, semantic_id, window_id, False, False, code, str(exc), [before, after], approval_id)
            return ActionResult(success=False, verified=False, error_code=code, before_snapshot_id=before,
                                after_snapshot_id=after, evidence=[e for e in (before, after) if e])

        after = self._snapshot(window_id)
        predicate = self.verifiers.get(verification or self._verification_for(semantic_id))
        verified = bool(predicate(window_id, selector, args)) if predicate else False
        self._record(action, semantic_id, window_id, True, verified, None, None, [before, after], approval_id)
        return ActionResult(success=True, verified=verified, before_snapshot_id=before,
                            after_snapshot_id=after, evidence=[e for e in (before, after) if e])

    def _act(self, window_id: str, action: str, selector: str, args: dict) -> None:
        if action in ("click", "invoke"):
            self.channel.click(window_id, selector)
        elif action == "type":
            self.channel.focus(window_id, selector)
            self.channel.insert_text(window_id, str(args.get("text", "")))
        elif action == "select":
            self.channel.select(window_id, selector, str(args.get("value", "")))

    def _verification_for(self, semantic_id: str) -> str:
        locator = getattr(self.resolver, "registry", {}).get(semantic_id)
        return getattr(locator, "verification", "")

    def _failed(self, action: str, semantic_id: str, code: str, message: str,
                window_id: str | None = None) -> ActionResult:
        self._record(action, semantic_id, window_id, False, False, code, message, [], None)
        return ActionResult(success=False, verified=False, error_code=code, before_snapshot_id="",
                            after_snapshot_id="")

    def _record(self, action, semantic_id, window_id, success, verified, code, message, evidence,
                approval_id) -> None:
        if self.store is None:
            return
        self.store.record("action", {"semantic_id": semantic_id, "action": action, "success": success,
                                     "verified": verified, "error_code": code, "message": message},
                          evidence_paths=evidence, window_id=window_id, semantic_id=semantic_id,
                          action=action, approval_id=approval_id)

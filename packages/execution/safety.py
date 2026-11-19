"""Window whitelist, pre-action identity checks, approval tokens for high-impact controls.

Merged surface: the gate holds an `EventStore` and records a pending request whenever a human
decision is missing; an `identity_checker` callback and an `approvals` object are accepted for the
call sites that arrive from the perception lane. Failure types are shared so a caller can catch
either the category (`ApprovalRequired`) or the code (`exc.code`) without knowing which lane
wrote the check.
"""

from events.store import ApprovalError, EventStore

HIGH_IMPACT = {"approval_mode", "terminal", "delete", "install", "git_commit", "git_push"}


class SafetyError(RuntimeError):
    """One error type for both call shapes: `SafetyError("message")` or `SafetyError(code, message)`."""

    code = "window_not_allowed"

    def __init__(self, code: str, message: str | None = None):
        if message is None:
            code, message = self.code, code
        super().__init__(message)
        self.code = code
        self.message = message


class ApprovalRequired(SafetyError):
    code = "approval_required"


class IdentityCheckFailed(SafetyError):
    code = "identity_mismatch"


def is_high_impact(semantic_id: str) -> bool:
    """docs/api.md: approval_mode / terminal / delete / install / git_* are gated, at any depth.

    A semantic id matches when one of its dotted parts is gated (`trae.git.commit`) or when a gated
    word simply appears in it (`trae.chat.approval_mode_toggle`). The second rule is the looser one
    and it is kept deliberately: a gate that misses a new control name must fail closed.
    """
    lowered = (semantic_id or "").lower()
    parts = lowered.split(".")
    return (any(part in HIGH_IMPACT or part.startswith("git_") or part == "git" for part in parts)
            or any(token in lowered for token in HIGH_IMPACT))


class SafetyGate:
    def __init__(self, allowed_windows: set[str], store: EventStore | None = None,
                 identity_checker=None, approvals: EventStore | None = None):
        self.allowed_windows = set(allowed_windows)
        self.store = store if store is not None else approvals
        self.approvals = self.store
        self.identity_checker = identity_checker

    def allow(self, window_id: str) -> None:
        self.allowed_windows.add(window_id)

    def revoke(self, window_id: str) -> None:
        self.allowed_windows.discard(window_id)

    def check_window(self, window_id: str) -> None:
        if window_id not in self.allowed_windows:
            raise SafetyError("window_not_allowed", f"window {window_id} is not whitelisted")

    def check_identity(self, observed: dict, expected: dict) -> None:
        """Re-verify the target before acting: never act on a window we did not choose."""
        for field in ("process_name", "window_id"):
            want = expected.get(field)
            if want and observed.get(field) != want:
                raise IdentityCheckFailed("identity_mismatch",
                                          f"{field} expected {want!r}, observed {observed.get(field)!r}")
        suffix = expected.get("title_suffix")
        if suffix and not str(observed.get("title", "")).endswith(suffix):
            raise IdentityCheckFailed("identity_mismatch", f"title does not end with {suffix!r}")

    def check_action(self, window_id: str, semantic_id: str, action: str,
                     approval_token: str | None) -> str | None:
        """Return the approval id spent on a high-impact action, or None when nothing was gated."""
        self.check_window(window_id)
        if self.identity_checker is not None:
            try:
                self.identity_checker(window_id)
            except SafetyError:
                raise
            except Exception as exc:
                raise IdentityCheckFailed("identity_mismatch", f"{window_id}: {exc}") from exc
        if not is_high_impact(semantic_id):
            return None
        scope = {"window_id": window_id, "semantic_ids": [semantic_id], "actions": [action]}
        if not approval_token:
            if self.store:
                self.store.request_approval(scope, f"high-impact action {action} on {semantic_id}")
            raise ApprovalRequired("approval_required", f"{semantic_id} requires an approval token")
        if self.store is None:
            raise ApprovalRequired("approval_required", "no event store configured to validate approvals")
        try:
            return self.store.consume_approval(approval_token, window_id, semantic_id, action)
        except ApprovalError as exc:
            raise ApprovalRequired(exc.code, exc.message) from exc

"""Window whitelist, pre-action identity checks, approval tokens for high-impact controls."""

from events.store import ApprovalError, EventStore

HIGH_IMPACT = {"approval_mode", "terminal", "delete", "install", "git_commit", "git_push"}


class SafetyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_high_impact(semantic_id: str) -> bool:
    """docs/api.md: approval_mode / terminal / delete / install / git_* are gated, at any depth."""
    parts = semantic_id.split(".")
    return any(part in HIGH_IMPACT or part.startswith("git_") or part == "git" for part in parts)


class SafetyGate:
    def __init__(self, allowed_windows: set[str], store: EventStore | None = None):
        self.allowed_windows = set(allowed_windows)
        self.store = store

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
                raise SafetyError("identity_mismatch",
                                  f"{field} expected {want!r}, observed {observed.get(field)!r}")
        suffix = expected.get("title_suffix")
        if suffix and not str(observed.get("title", "")).endswith(suffix):
            raise SafetyError("identity_mismatch", f"title does not end with {suffix!r}")

    def check_action(self, window_id: str, semantic_id: str, action: str,
                     approval_token: str | None) -> str | None:
        self.check_window(window_id)
        if not is_high_impact(semantic_id):
            return None
        scope = {"window_id": window_id, "semantic_ids": [semantic_id], "actions": [action]}
        if not approval_token:
            if self.store:
                self.store.request_approval(scope, f"high-impact action {action} on {semantic_id}")
            raise SafetyError("approval_required", f"{semantic_id} requires an approval token")
        if self.store is None:
            raise SafetyError("approval_required", "no event store configured to validate approvals")
        try:
            return self.store.consume_approval(approval_token, window_id, semantic_id, action)
        except ApprovalError as exc:
            raise SafetyError(exc.code, exc.message) from exc

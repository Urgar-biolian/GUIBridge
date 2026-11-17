"""Window whitelist, pre-action identity checks, approval tokens for high-impact controls."""

HIGH_IMPACT = {"approval_mode", "terminal", "delete", "install", "git_commit", "git_push"}


class SafetyError(RuntimeError):
    code = "window_not_allowed"


class ApprovalRequired(SafetyError):
    code = "approval_required"


class IdentityCheckFailed(SafetyError):
    code = "identity_mismatch"


def is_high_impact(semantic_id: str) -> bool:
    lowered = (semantic_id or "").lower()
    return any(token in lowered for token in HIGH_IMPACT)


class SafetyGate:
    def __init__(self, allowed_windows: set[str], identity_checker=None, approvals=None):
        self.allowed_windows = allowed_windows
        self.identity_checker = identity_checker
        self.approvals = approvals

    def check_action(self, window_id: str, semantic_id: str, action: str,
                     approval_token: str | None) -> str | None:
        """Raise SafetyError subtypes; return the approval_id used for high-impact actions."""
        if window_id not in self.allowed_windows:
            raise SafetyError(f"window {window_id} not whitelisted")
        if self.identity_checker is not None:
            try:
                self.identity_checker(window_id)
            except SafetyError:
                raise
            except Exception as e:
                raise IdentityCheckFailed(f"{window_id}: {e}") from e
        if not is_high_impact(semantic_id):
            return None
        if not approval_token or self.approvals is None:
            raise ApprovalRequired(f"{semantic_id}: approval token required")
        try:
            return self.approvals.consume_approval(approval_token, semantic_id, action)
        except Exception as e:
            raise ApprovalRequired(str(e)) from e

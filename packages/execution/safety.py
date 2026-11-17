"""Window whitelist, pre-action identity checks, approval tokens for high-impact controls."""

HIGH_IMPACT = {"approval_mode", "terminal", "delete", "install", "git_commit", "git_push"}


class SafetyGate:
    def __init__(self, allowed_windows: set[str]):
        self.allowed_windows = allowed_windows

    def check_action(self, window_id: str, semantic_id: str, action: str,
                     approval_token: str | None) -> None:
        raise NotImplementedError("S2")
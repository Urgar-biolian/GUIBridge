"""Trae adapter: IDE-mode precondition, manual approval default, submit->status->read state machine."""

from adapters.base import AppAdapter


class TraeAdapter(AppAdapter):
    app = "trae"

    def ensure_ide_mode(self) -> None:
        raise NotImplementedError("S2")

    def select_chat_mode(self, mode: str) -> None:
        raise NotImplementedError("S2")

    def force_manual_approval(self) -> None:
        raise NotImplementedError("S2")
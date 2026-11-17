"""Adapter interface: capability probe + business-level task operations.

The `Channel` / `ElementResolver` / `Snapshotter` protocols below are the surfaces S2 needs from
the S1 perception engine. They are integration contracts, not implementations: at gate G1 the A-line
`semantic.resolver` + `perception.cdp` are injected here unchanged (docs/team-plan.md §3).
"""

from typing import Protocol

from semantic.element import GUIElement, TaskRecord


class Channel(Protocol):
    """A perception channel that can act on and read a target window by selector."""

    name: str

    def available(self) -> bool: ...

    def window_identity(self, window_id: str) -> dict:
        """{window_id, process_name, title, geometry} for pre-action identity checks."""

    def find(self, window_id: str, selector: str) -> dict | None:
        """{selector, role, name, text, rect, disabled, classes} or None when absent."""

    def query(self, window_id: str, selector: str) -> list[dict]: ...

    def scan(self, window_id: str, max_depth: int = 18) -> list[dict]: ...

    def screenshot(self, window_id: str) -> str | None:
        """Path to a target-window-only capture; never a full desktop shot (PRD §9)."""

    def click(self, window_id: str, selector: str) -> None: ...

    def focus(self, window_id: str, selector: str) -> None: ...

    def insert_text(self, window_id: str, text: str) -> None: ...

    def select(self, window_id: str, selector: str, value: str) -> None:
        """Open a menu and pick the leaf entry whose text matches `value` exactly (PROBE_REPORT F5/F9)."""

    def inner_text(self, window_id: str, selector: str) -> str: ...


class ElementResolver(Protocol):
    """semantic_id -> live element. Must relocate on every call (PRD §5, framework.md)."""

    def resolve(self, window_id: str, semantic_id: str) -> GUIElement: ...


class Snapshotter(Protocol):
    def capture(self, window_id: str) -> dict:
        """{snapshot_id, image_path, elements}; registers the window identity it observed."""


class AppAdapter:
    app: str = ""

    def capabilities(self) -> dict[str, str]:
        """Business capabilities this adapter exposes, for tool discovery and docs."""
        return {}

    def probe_channels(self) -> dict[str, bool]:
        """Probe each candidate channel; unreliable channels degrade to fallback, never primary."""
        raise NotImplementedError("S2")

    def send_task(self, project_path: str, task: str, mode: str = "chat",
                  allow_files: list[str] | None = None, acceptance: dict | None = None) -> TaskRecord:
        raise NotImplementedError("S2")

    def get_status(self, task_id: str) -> TaskRecord:
        raise NotImplementedError("S2")

    def read_result(self, task_id: str, max_chars: int = 8000) -> dict:
        raise NotImplementedError("S2")

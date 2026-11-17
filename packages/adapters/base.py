"""Adapter interface: capability probe + business-level task operations."""

from semantic.element import TaskRecord


class AppAdapter:
    app: str = ""

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
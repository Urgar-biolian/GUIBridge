"""SQLite event store: actions, state transitions, snapshot/screenshot evidence, approvals."""


class EventStore:
    def __init__(self, db_path: str, retention_days: int = 30):
        self.db_path = db_path
        self.retention_days = retention_days

    def record(self, kind: str, payload: dict, evidence_paths: list[str] | None = None) -> str:
        raise NotImplementedError("S2")

    def task_transitions(self, task_id: str) -> list[dict]:
        raise NotImplementedError("S2")
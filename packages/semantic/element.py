from dataclasses import dataclass, field


@dataclass
class GUIElement:
    id: str
    window_id: str
    role: str
    name: str
    bounds: tuple[int, int, int, int]
    actions: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    confidence: float = 0.0
    calibrated: bool = False
    semantic_id: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class Locator:
    semantic_id: str
    app_version: str
    chain: list[dict] = field(default_factory=list)
    verification: str = ""
    healed_at: str | None = None


@dataclass
class ActionResult:
    success: bool
    verified: bool
    before_snapshot_id: str
    after_snapshot_id: str
    error_code: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class TaskRecord:
    task_id: str
    app: str
    state: str = "unknown"
    transitions: list[dict] = field(default_factory=list)

    def transition(self, state: str, evidence_id: str, ts: str) -> None:
        self.state = state
        self.transitions.append({"state": state, "evidence_id": evidence_id, "ts": ts})
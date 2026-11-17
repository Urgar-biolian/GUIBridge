"""Trae adapter: IDE-mode precondition, manual approval default, submit->status->read state machine."""

import time
import uuid
from datetime import datetime, timezone

from adapters.base import AppAdapter
from adapters.trae import states
from semantic.element import TaskRecord

SESSION_MODE = {"chat": "Chat", "agent": "Agent"}


class AdapterError(Exception):
    def __init__(self, code: str, message: str, failure_class: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.failure_class = failure_class or code


class TraeAdapter(AppAdapter):
    app = "trae"

    def __init__(self, window_id: str, channel, executor, store, registry: dict, app_version: str = "3.6.13",
                 status_timeout: float = 300.0, stop_control_selector: str | None = None):
        self.window_id = window_id
        self.channel = channel
        self.executor = executor
        self.store = store
        self.registry = registry
        self.app_version = app_version
        self.status_timeout = status_timeout
        self.stop_control_selector = stop_control_selector
        self.snapshots = executor.snapshots
        self.tasks: dict[str, dict] = {}

    def capabilities(self) -> dict[str, str]:
        return {"send_task": "chat|agent", "get_status": "conversation text signals",
                "read_result": "cdp conversation innerText"}

    def probe_channels(self) -> dict[str, bool]:
        """PROBE_REPORT F4: `trae chat` delivers silently on 3.6.13, so it stays a candidate only."""
        return {"cdp": bool(self.channel.available()), "cli_chat": False, "reply_archive": False}

    # preconditions

    def ensure_ide_mode(self) -> None:
        result = self._perform("trae.mode.ide_tab", "click")
        self._require(result, "ide_layout_visible", "locator_missing")

    def select_chat_mode(self, mode: str) -> None:
        if mode not in SESSION_MODE:
            raise AdapterError("locator_missing", f"unsupported session mode {mode!r}")
        leaf = SESSION_MODE[mode]
        self._require(self._perform("trae.chat.mode_entry", "click"), "mode_menu_open", "locator_missing")
        result = self._perform("trae.chat.mode_entry", "select", {"value": leaf},
                               verification="session_mode_selected")
        self._require(result, "session_mode_selected", "not_submitted")

    def force_manual_approval(self, approval_token: str | None = None) -> str:
        """Read the approval trigger, switch only when it reads auto, and never leave the outcome unsaid.

        F9 is why this may not return silently: a mis-clicked mode menu once ran an Agent task under
        auto-approval. F10 is why the outcome can be `unverified:*`: on the probed build the trigger's
        menu does not open over CDP, so a click is not always confirmable. An unreadable label is
        recorded and only fatal for agent mode; an approved switch that fails to produce a readable
        manual label stays fatal, because a human already granted it.
        """
        state = self._read_approval_state()
        if state == "manual":
            return self._record_approval_read("manual_confirmed", state, clicked=False)
        if state == "auto":
            result = self._perform("trae.chat.approval_mode", "click", approval_token=approval_token)
            if not result.verified:
                self._record_approval_read("unverified:menu_not_confirmed", state, clicked=True)
                raise AdapterError(result.error_code or "approval_required",
                                   f"approval mode post-condition not satisfied: "
                                   f"{result.error_code or 'unknown reason'}")
            after = self._read_approval_state()
            if after != "manual":
                self._record_approval_read("unverified:manual_label_unreadable", after, clicked=True)
                raise AdapterError("approval_required",
                                   f"approval mode still reads {after!r} after an approved switch")
            return self._record_approval_read("manual_confirmed", after, clicked=True)
        return self._record_approval_read(f"unverified:trigger_{state}", state, clicked=False)

    def _read_approval_state(self) -> str:
        return states.approval_state(
            bool(self.channel.find(self.window_id, states.AUTO_APPROVAL_TRIGGER)),
            bool(self.channel.find(self.window_id, states.MANUAL_APPROVAL_TRIGGER)),
            bool(self.channel.find(self.window_id, states.APPROVAL_TRIGGER_CLASS)),
        )

    def _record_approval_read(self, outcome: str, state: str, clicked: bool) -> str:
        self.store.record("approval_mode_read", {"outcome": outcome, "trigger_state": state,
                                                 "clicked": clicked, "ts": _iso()},
                          window_id=self.window_id)
        return outcome

    # task operations

    def send_task(self, project_path: str, task: str, mode: str = "chat",
                  allow_files: list[str] | None = None, acceptance: dict | None = None,
                  approval_token: str | None = None, allow_auto_approval: bool = False) -> TaskRecord:
        if mode == "agent" and not approval_token:
            raise AdapterError("approval_required", "agent mode needs an explicit approval token")
        if not self.probe_channels()["cdp"]:
            raise AdapterError("unknown_state", "no reliable CDP channel; refusing a coordinate fallback")

        task_id = "task_" + uuid.uuid4().hex[:12]
        self.store.create_task(task_id, self.app, project_path, mode,
                               {"allow_files": allow_files or [], "acceptance": acceptance or {}})
        rec = TaskRecord(task_id=task_id, app=self.app)
        self.tasks[task_id] = {"record": rec, "project_path": project_path, "mode": mode,
                               "task_text": task, "started": time.time(), "deadline": time.time() + self.status_timeout}

        try:
            self.ensure_ide_mode()
            self.select_chat_mode(mode)
            if allow_auto_approval:
                approval_read = "auto_allowed"
            else:
                approval_read = self.force_manual_approval(approval_token)
                if mode == "agent" and approval_read != "manual_confirmed":
                    raise AdapterError("approval_required",
                                       f"agent mode needs the manual approval label confirmed, "
                                       f"read {approval_read!r}")
            self.tasks[task_id]["approval_mode_read"] = approval_read
            self._perform("trae.chat.new_session", "click")
            typed = self._perform("trae.chat.composer", "type", {"text": task})
            self._require(typed, "focusable", "not_submitted", failure_class="focus_failed")
            sent = self._perform("trae.chat.send_button", "click", {"text": task})
        except AdapterError as exc:
            self._fail(rec, exc.code, exc.message, exc.failure_class)
            raise
        if not sent.verified:
            self._fail(rec, sent.error_code or "not_submitted", "user message did not appear in the conversation",
                       "not_submitted")
            raise AdapterError(sent.error_code or "not_submitted",
                               "user message did not appear in the conversation", failure_class="not_submitted")
        self._transition(rec, "submitted", sent.after_snapshot_id)
        return rec

    def get_status(self, task_id: str) -> TaskRecord:
        entry = self._entry(task_id)
        rec: TaskRecord = entry["record"]
        if rec.state in ("verified", "failed"):
            return rec
        conversation = self._conversation()
        tail = self._reply_tail(conversation, entry["task_text"])
        stop_present = bool(self.stop_control_selector) and \
            self.channel.find(self.window_id, self.stop_control_selector) is not None
        entry["signals"] = states.collect_signals(tail, stop_present)
        state = states.detect_state(tail, stop_present, bool(tail.strip()), False)
        if state == "unknown" and time.time() > entry["deadline"]:
            self._transition(rec, "unknown", self._snapshot_id())
            self.store.record("status_timeout", {"task_id": task_id, "error_code": "unknown_state",
                                                 "deadline_ts": _iso()}, task_id=task_id,
                              window_id=self.window_id)
        elif state != rec.state:
            self._transition(rec, state, self._snapshot_id())
        return rec

    def last_signals(self, task_id: str) -> dict:
        return self._entry(task_id).get("signals", {})

    def read_result(self, task_id: str, max_chars: int = 8000) -> dict:
        entry = self._entry(task_id)
        conversation = self._conversation()
        tail = self._reply_tail(conversation, entry["task_text"])
        evidence = self._snapshot_id()
        truncated = len(tail) > max_chars
        claimed_done = entry["record"].state in ("claimed_done", "verified")
        if not claimed_done:
            self.store.record("read_result", {"task_id": task_id, "claimed_done": False,
                                              "note": "reply read before claimed_done; state unchanged"},
                              evidence_paths=[evidence], task_id=task_id, window_id=self.window_id)
        return {"task_id": task_id, "reply_text": tail[:max_chars], "untrusted": True,
                "claimed_done": claimed_done, "truncated": truncated, "full_length": len(tail),
                "evidence": [evidence]}

    def verify(self, task_id: str, evidence_id: str) -> TaskRecord:
        """Only the independent verifier may lift a task to `verified` (docs/sql.md)."""
        rec = self._entry(task_id)["record"]
        self._transition(rec, "verified", evidence_id, actor="verifier")
        return rec

    # internals

    def _entry(self, task_id: str) -> dict:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise AdapterError("unknown_state", f"no such task in this session: {task_id}") from exc

    def _selector(self, semantic_id: str) -> str:
        try:
            return states.cdp_selector(self.registry, semantic_id)
        except LookupError as exc:
            raise AdapterError("locator_missing", str(exc)) from exc

    def _perform(self, semantic_id: str, action: str, args: dict | None = None,
                 approval_token: str | None = None, verification: str | None = None):
        try:
            return self.executor.perform(self.window_id, semantic_id, action, args, approval_token,
                                         verification=verification)
        except Exception as exc:
            code = getattr(exc, "code", "locator_missing")
            raise AdapterError(code, str(exc)) from exc

    def _require(self, result, verification: str, code: str, failure_class: str | None = None) -> None:
        if result.verified:
            return
        raise AdapterError(result.error_code or code,
                           f"{verification} post-condition not satisfied for {result.error_code or 'unknown reason'}",
                           failure_class=failure_class)

    def _conversation(self) -> str:
        return self.channel.inner_text(self.window_id, self._selector("trae.chat.conversation"))

    @staticmethod
    def _reply_tail(conversation: str, task_text: str) -> str:
        at = conversation.rfind(task_text.strip())
        return conversation[at + len(task_text.strip()):] if at >= 0 else ""

    def _snapshot_id(self) -> str:
        if self.snapshots is None:
            return ""
        return self.snapshots.capture(self.window_id)["snapshot_id"]

    def _transition(self, rec: TaskRecord, state: str, evidence_id: str, actor: str = "adapter") -> None:
        rec.transition(state, evidence_id, _iso())
        self.store.set_task_state(rec.task_id, state, evidence_id, actor=actor)
        self.store.record("task_state", {"task_id": rec.task_id, "state": state},
                          evidence_paths=[evidence_id] if evidence_id else [], task_id=rec.task_id,
                          window_id=self.window_id)

    def _fail(self, rec: TaskRecord, code: str, message: str, failure_class: str | None = None) -> None:
        evidence = self._snapshot_id()
        self._transition(rec, "failed", evidence)
        self.store.record("task_failed", {"task_id": rec.task_id, "error_code": code, "message": message,
                                          "failure_class": failure_class},
                          evidence_paths=[evidence] if evidence else [], task_id=rec.task_id,
                          window_id=self.window_id)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

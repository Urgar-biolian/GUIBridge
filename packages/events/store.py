"""SQLite event store: actions, state transitions, snapshot/screenshot evidence, approvals.

Append-only for events, snapshots and task_transitions (docs/sql.md). `verified` may only be
written by the independent verifier. Approval tokens are stored hashed and are single-use.
"""

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

TASK_STATES = ("submitted", "running", "awaiting_approval", "claimed_done", "verified", "failed", "unknown")


class ApprovalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(raw: str | None):
    return json.loads(raw) if raw else None


def _new_id() -> str:
    return uuid.uuid4().hex


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _Serialized:
    """One connection shared across threads.

    The MCP SDK executes synchronous tools in a worker thread while the control plane writes from the
    event loop. `sqlite3.threadsafety == 3` makes the driver calls themselves safe; the lock keeps a
    composite write (row + audit event, grant + record) from interleaving with another.
    """

    def __init__(self, conn):
        self._conn = conn
        self._lock = threading.RLock()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, parameters=()):
        with self._lock:
            return self._conn.execute(sql, parameters)

    def executescript(self, sql):
        with self._lock:
            return self._conn.executescript(sql)

    def commit(self):
        with self._lock:
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()


class EventStore:
    def __init__(self, db_path: str, retention_days: int = 30):
        self.db_path = str(db_path)
        self.retention_days = retention_days
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self.conn = _Serialized(conn)
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # windows

    def register_window(self, window_id: str, process_name: str, title: str, geometry: dict,
                        whitelisted: bool | None = None) -> None:
        now = _ts(_now())
        row = self.conn.execute("SELECT whitelisted FROM windows WHERE window_id=?", (window_id,)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO windows VALUES (?,?,?,?,?,?,?)",
                (window_id, process_name, title, _dump(geometry), int(bool(whitelisted)), now, now),
            )
        else:
            keep = row["whitelisted"] if whitelisted is None else int(bool(whitelisted))
            self.conn.execute(
                "UPDATE windows SET process_name=?, title=?, geometry_json=?, whitelisted=?, last_seen=? "
                "WHERE window_id=?",
                (process_name, title, _dump(geometry), int(bool(keep)), now, window_id),
            )
        self.conn.commit()

    def list_windows(self, only_whitelisted: bool = False) -> list[dict]:
        sql = "SELECT * FROM windows" + (" WHERE whitelisted=1" if only_whitelisted else "")
        return [self._window_row(r) for r in self.conn.execute(sql + " ORDER BY last_seen")]

    def get_window(self, window_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM windows WHERE window_id=?", (window_id,)).fetchone()
        return self._window_row(r) if r else None

    def set_whitelisted(self, window_id: str, allowed: bool) -> None:
        cur = self.conn.execute("UPDATE windows SET whitelisted=? WHERE window_id=?", (int(bool(allowed)), window_id))
        self.conn.commit()
        if cur.rowcount == 0:
            raise KeyError(window_id)

    @staticmethod
    def _window_row(r: sqlite3.Row) -> dict:
        return {"window_id": r["window_id"], "process_name": r["process_name"], "title": r["title"],
                "geometry": _load(r["geometry_json"]), "whitelisted": bool(r["whitelisted"]),
                "first_seen": r["first_seen"], "last_seen": r["last_seen"]}

    # snapshots

    def add_snapshot(self, window_id: str, elements: list, image_path: str | None = None) -> str:
        snapshot_id = "snap_" + _new_id()[:16]
        self.conn.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                          (snapshot_id, window_id, _ts(_now()), image_path, _dump(elements)))
        self.conn.commit()
        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not r:
            return None
        return {"snapshot_id": r["snapshot_id"], "window_id": r["window_id"], "ts": r["ts"],
                "image_path": r["image_path"], "elements": _load(r["elements_json"])}

    # tasks

    def create_task(self, task_id: str, app: str, project_path: str, mode: str = "chat",
                    acceptance: dict | None = None) -> dict:
        now = _ts(_now())
        self.conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                          (task_id, app, project_path, mode, "unknown", _dump(acceptance) if acceptance else None,
                           now, now))
        self.conn.commit()
        return {"task_id": task_id, "app": app, "project_path": project_path, "mode": mode,
                "state": "unknown", "acceptance": acceptance, "created_ts": now, "updated_ts": now}

    def get_task(self, task_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not r:
            return None
        return {"task_id": r["task_id"], "app": r["app"], "project_path": r["project_path"], "mode": r["mode"],
                "state": r["state"], "acceptance": _load(r["acceptance_json"]),
                "created_ts": r["created_ts"], "updated_ts": r["updated_ts"],
                "transitions": self.task_transitions(task_id)}

    def list_tasks(self) -> list[dict]:
        ids = [r["task_id"] for r in self.conn.execute("SELECT task_id FROM tasks ORDER BY created_ts")]
        return [t for t in (self.get_task(i) for i in ids) if t]

    def set_task_state(self, task_id: str, state: str, evidence_id: str, actor: str = "adapter") -> None:
        if state not in TASK_STATES:
            raise ValueError(f"unknown task state: {state}")
        if state == "verified" and actor != "verifier":
            raise PermissionError("verified may only be granted by the independent verifier (docs/sql.md)")
        now = _ts(_now())
        self.conn.execute("INSERT INTO task_transitions (task_id, state, evidence_id, ts) VALUES (?,?,?,?)",
                          (task_id, state, evidence_id, now))
        self.conn.execute("UPDATE tasks SET state=?, updated_ts=? WHERE task_id=?", (state, now, task_id))
        self.conn.commit()

    def task_transitions(self, task_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT state, evidence_id, ts FROM task_transitions WHERE task_id=? ORDER BY id", (task_id,))
        return [{"state": r["state"], "evidence_id": r["evidence_id"], "ts": r["ts"]} for r in rows]

    # events

    def record(self, kind: str, payload: dict, evidence_paths: list[str] | None = None, task_id: str | None = None,
               window_id: str | None = None, semantic_id: str | None = None, action: str | None = None,
               approval_id: str | None = None) -> str:
        event_id = "ev_" + _new_id()[:16]
        if window_id is not None and not self.conn.execute(
                "SELECT 1 FROM windows WHERE window_id=?", (window_id,)).fetchone():
            # An approval can reference a window we have observed but not yet snapshotted; the schema
            # keeps windows as the identity table, so carry the id in the payload instead of the FK.
            payload = {**payload, "window_id_unregistered": window_id}
            window_id = None
        self.conn.execute(
            "INSERT INTO events (event_id, ts, kind, task_id, window_id, semantic_id, action, payload_json, "
            "evidence_json, approval_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, _ts(_now()), kind, task_id, window_id, semantic_id, action, _dump(payload),
             _dump(evidence_paths or []), approval_id))
        self.conn.commit()
        return event_id

    def events(self, task_id: str | None = None, window_id: str | None = None, kind: str | None = None,
               since: str | None = None, after_seq: int = 0, limit: int = 500) -> list[dict]:
        where, params = ["rowid>?"], [after_seq]
        if task_id:
            where.append("task_id=?"); params.append(task_id)
        if window_id:
            where.append("window_id=?"); params.append(window_id)
        if kind:
            where.append("kind=?"); params.append(kind)
        if since:
            where.append("ts>=?"); params.append(since)
        sql = "SELECT rowid, * FROM events WHERE " + " AND ".join(where) + " ORDER BY rowid LIMIT ?"
        params.append(limit)
        return [{"seq": r["rowid"], "event_id": r["event_id"], "ts": r["ts"], "kind": r["kind"],
                 "task_id": r["task_id"], "window_id": r["window_id"], "semantic_id": r["semantic_id"],
                 "action": r["action"], "payload": _load(r["payload_json"]),
                 "evidence": _load(r["evidence_json"]) or [], "approval_id": r["approval_id"]}
                for r in self.conn.execute(sql, params)]

    def get_event(self, event_id: str) -> dict | None:
        r = self.conn.execute("SELECT rowid, * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if not r:
            return None
        return {"seq": r["rowid"], "event_id": r["event_id"], "ts": r["ts"], "kind": r["kind"],
                "task_id": r["task_id"], "window_id": r["window_id"], "semantic_id": r["semantic_id"],
                "action": r["action"], "payload": _load(r["payload_json"]),
                "evidence": _load(r["evidence_json"]) or [], "approval_id": r["approval_id"]}

    # approvals

    def request_approval(self, scope: dict, reason: str) -> str:
        request_id = "req_" + _new_id()[:12]
        self.record("approval_requested", {"request_id": request_id, "scope": scope, "reason": reason},
                    window_id=scope.get("window_id"))
        return request_id

    def grant_approval(self, scope: dict, granted_by: str = "user", ttl_seconds: int = 600,
                       request_id: str | None = None) -> str:
        token = _new_id() + _new_id()
        now = _now()
        approval_id = "apv_" + _new_id()[:12]
        self.conn.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,0)",
                          (approval_id, _ts(now), _dump(scope), hash_token(token), granted_by,
                           _ts(now + timedelta(seconds=ttl_seconds))))
        self.conn.commit()
        self.record("approval_granted", {"approval_id": approval_id, "scope": scope, "request_id": request_id,
                                        "granted_by": granted_by, "expires_ts": _ts(now + timedelta(seconds=ttl_seconds))},
                    window_id=scope.get("window_id"), approval_id=approval_id)
        return token

    def consume_approval(self, token: str, window_id: str, semantic_id: str, action: str) -> str:
        row = self.conn.execute("SELECT * FROM approvals WHERE token_hash=? AND used=0",
                               (hash_token(token),)).fetchone()
        if row is None or row["expires_ts"] < _ts(_now()):
            raise ApprovalError("approval_required", "no valid approval token for this action")
        scope = _load(row["scope_json"]) or {}
        if not _scope_allows(scope, window_id, semantic_id, action):
            raise ApprovalError("approval_required", "approval token does not cover this scope")
        self.conn.execute("UPDATE approvals SET used=1 WHERE approval_id=?", (row["approval_id"],))
        self.conn.commit()
        self.record("approval_consumed", {"approval_id": row["approval_id"], "window_id": window_id,
                                         "semantic_id": semantic_id, "action": action},
                    window_id=window_id, semantic_id=semantic_id, action=action, approval_id=row["approval_id"])
        return row["approval_id"]

    def list_approvals(self) -> list[dict]:
        now = _ts(_now())
        return [{"approval_id": r["approval_id"], "ts": r["ts"], "scope": _load(r["scope_json"]),
                 "granted_by": r["granted_by"], "expires_ts": r["expires_ts"], "used": bool(r["used"]),
                 "expired": r["expires_ts"] < now}
                for r in self.conn.execute("SELECT * FROM approvals ORDER BY ts")]

    def pending_approvals(self) -> list[dict]:
        granted = {e["payload"].get("request_id") for e in self.events(kind="approval_granted", limit=1000)}
        return [e for e in self.events(kind="approval_requested", limit=1000)
                if e["payload"].get("request_id") not in granted]

    # locator registry + heal patches

    def save_locator(self, semantic_id: str, app: str, app_version: str, chain: list, verification: str,
                     healed_at: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO locators (semantic_id, app, app_version, chain_json, verification, healed_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(semantic_id, app, app_version) "
            "DO UPDATE SET chain_json=excluded.chain_json, verification=excluded.verification, "
            "healed_at=excluded.healed_at",
            (semantic_id, app, app_version, _dump(chain), verification, healed_at))
        self.conn.commit()

    def list_locators(self, app: str | None = None, app_version: str | None = None) -> list[dict]:
        where, params = [], []
        if app:
            where.append("app=?"); params.append(app)
        if app_version:
            where.append("app_version=?"); params.append(app_version)
        sql = "SELECT * FROM locators" + ((" WHERE " + " AND ".join(where)) if where else "")
        return [{"semantic_id": r["semantic_id"], "app": r["app"], "app_version": r["app_version"],
                 "chain": _load(r["chain_json"]), "verification": r["verification"], "healed_at": r["healed_at"]}
                for r in self.conn.execute(sql + " ORDER BY semantic_id", params)]

    def propose_heal_patch(self, semantic_id: str, app: str, app_version: str, proposed_chain: list) -> str:
        patch_id = "heal_" + _new_id()[:12]
        self.conn.execute("INSERT INTO heal_patches VALUES (?,?,?,?,?,?,?,NULL)",
                          (patch_id, semantic_id, app, app_version, _dump(proposed_chain), "pending", _ts(_now())))
        self.conn.commit()
        self.record("heal_proposed", {"patch_id": patch_id, "semantic_id": semantic_id, "app_version": app_version,
                                      "proposed_chain": proposed_chain}, semantic_id=semantic_id)
        return patch_id

    def list_heal_patches(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM heal_patches" + (" WHERE status=?" if status else "") + " ORDER BY rowid"
        params = [status] if status else []
        return [{"patch_id": r["patch_id"], "semantic_id": r["semantic_id"], "app": r["app"],
                 "app_version": r["app_version"], "proposed_chain": _load(r["proposed_chain_json"]),
                 "status": r["status"], "created_ts": r["created_ts"], "reviewed_by": r["reviewed_by"]}
                for r in self.conn.execute(sql, params)]

    def review_heal_patch(self, patch_id: str, decision: str, reviewed_by: str) -> dict:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be approved or rejected")
        rows = [r for r in self.conn.execute("SELECT * FROM heal_patches WHERE patch_id=?", (patch_id,))]
        if not rows:
            raise KeyError(patch_id)
        patch = rows[0]
        if patch["status"] != "pending":
            raise PermissionError(f"patch already reviewed: {patch['status']}")
        self.conn.execute("UPDATE heal_patches SET status=?, reviewed_by=? WHERE patch_id=?",
                          (decision, reviewed_by, patch_id))
        if decision == "approved":
            self.save_locator(patch["semantic_id"], patch["app"], patch["app_version"],
                              _load(patch["proposed_chain_json"]), "", _ts(_now()))
        self.conn.commit()
        self.record("heal_reviewed", {"patch_id": patch_id, "semantic_id": patch["semantic_id"],
                                      "decision": decision, "reviewed_by": reviewed_by},
                    semantic_id=patch["semantic_id"])
        return {"patch_id": patch_id, "status": decision, "reviewed_by": reviewed_by}

    # retention

    def purge_expired(self) -> list[str]:
        cutoff = _ts(_now() - timedelta(days=self.retention_days))
        images = [r["image_path"] for r in self.conn.execute(
            "SELECT image_path FROM snapshots WHERE ts<? AND image_path IS NOT NULL", (cutoff,)) if r["image_path"]]
        self.conn.execute("DELETE FROM events WHERE ts<?", (cutoff,))
        self.conn.execute("DELETE FROM snapshots WHERE ts<?", (cutoff,))
        self.conn.commit()
        return images


def _scope_allows(scope: dict, window_id: str, semantic_id: str, action: str) -> bool:
    if scope.get("window_id") and scope["window_id"] != window_id:
        return False
    ids = scope.get("semantic_ids")
    if ids and semantic_id not in ids:
        return False
    actions = scope.get("actions")
    if actions and action not in actions:
        return False
    return True

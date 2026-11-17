"""SQLite event store: actions, state transitions, snapshot/screenshot evidence, approvals.

Append-only for events/snapshots. Approval tokens are stored hashed; plaintext is
returned once at creation time. Retention pruning only deletes old non-task events.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StoreError(RuntimeError):
    code = "unknown_state"


class ApprovalError(StoreError):
    code = "approval_required"


class EventStore:
    def __init__(self, db_path: str, retention_days: int = 30):
        self.db_path = db_path
        self.retention_days = retention_days
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- events ---------------------------------------------------------
    def record(self, kind: str, payload: dict, evidence: list[str] | None = None,
               task_id: str | None = None, window_id: str | None = None,
               semantic_id: str | None = None, action: str | None = None,
               approval_id: str | None = None) -> str:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        self._conn.execute(
            "INSERT INTO events (event_id, ts, kind, task_id, window_id, semantic_id, action,"
            " payload_json, evidence_json, approval_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, utcnow(), kind, task_id, window_id, semantic_id, action,
             json.dumps(payload, ensure_ascii=False), json.dumps(evidence or [], ensure_ascii=False),
             approval_id))
        self._conn.commit()
        return event_id

    def get_event(self, event_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._event_row(row) if row else None

    def latest_event(self, task_id: str, kind: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE task_id=? AND kind=? ORDER BY ts DESC, rowid DESC LIMIT 1",
            (task_id, kind)).fetchone()
        return self._event_row(row) if row else None

    def events_after(self, event_id: str | None = None, limit: int = 200) -> list[dict]:
        if event_id:
            row = self._conn.execute("SELECT rowid FROM events WHERE event_id=?", (event_id,)).fetchone()
            after = row["rowid"] if row else 0
        else:
            after = 0
        rows = self._conn.execute(
            "SELECT * FROM events WHERE rowid>? ORDER BY rowid LIMIT ?", (after, limit)).fetchall()
        return [self._event_row(r) for r in rows]

    @staticmethod
    def _event_row(row) -> dict:
        return {
            "event_id": row["event_id"], "ts": row["ts"], "kind": row["kind"],
            "task_id": row["task_id"], "window_id": row["window_id"],
            "semantic_id": row["semantic_id"], "action": row["action"],
            "payload": json.loads(row["payload_json"]),
            "evidence": json.loads(row["evidence_json"]),
            "approval_id": row["approval_id"],
        }

    def prune(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        cur = self._conn.execute(
            "DELETE FROM events WHERE ts<? AND task_id IS NULL", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    # -- tasks ----------------------------------------------------------
    def create_task(self, task_id: str, app: str, project_path: str, mode: str,
                    acceptance: dict | None = None) -> None:
        now = utcnow()
        self._conn.execute(
            "INSERT INTO tasks (task_id, app, project_path, mode, state, acceptance_json,"
            " created_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?)",
            (task_id, app, project_path, mode, "unknown",
             json.dumps(acceptance or {}, ensure_ascii=False), now, now))
        self._conn.commit()

    def transition(self, task_id: str, state: str, evidence_id: str = "") -> None:
        now = utcnow()
        self._conn.execute(
            "INSERT INTO task_transitions (task_id, state, evidence_id, ts) VALUES (?,?,?,?)",
            (task_id, state, evidence_id, now))
        self._conn.execute("UPDATE tasks SET state=?, updated_ts=? WHERE task_id=?",
                           (state, now, task_id))
        self._conn.commit()

    def get_task(self, task_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        return {
            "task_id": row["task_id"], "app": row["app"],
            "project_path": row["project_path"], "mode": row["mode"],
            "state": row["state"], "acceptance": json.loads(row["acceptance_json"] or "{}"),
            "created_ts": row["created_ts"], "updated_ts": row["updated_ts"],
            "transitions": self.task_transitions(task_id),
        }

    def list_tasks(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT task_id FROM tasks ORDER BY created_ts DESC LIMIT ?", (limit,)).fetchall()
        return [self.get_task(r["task_id"]) for r in rows]

    def task_transitions(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT state, evidence_id, ts FROM task_transitions WHERE task_id=? ORDER BY id",
            (task_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- snapshots ------------------------------------------------------
    def add_snapshot(self, window_id: str, elements_summary, image_path: str | None = None) -> str:
        snapshot_id = f"snap_{uuid.uuid4().hex[:16]}"
        self._conn.execute(
            "INSERT INTO snapshots (snapshot_id, window_id, ts, image_path, elements_json)"
            " VALUES (?,?,?,?,?)",
            (snapshot_id, window_id, utcnow(), image_path,
             json.dumps(elements_summary, ensure_ascii=False)))
        self._conn.commit()
        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        return {"snapshot_id": row["snapshot_id"], "window_id": row["window_id"],
                "ts": row["ts"], "image_path": row["image_path"],
                "elements": json.loads(row["elements_json"])}

    # -- approvals ------------------------------------------------------
    def create_approval(self, scope: dict, granted_by: str = "local-user",
                        ttl_seconds: int = 600) -> dict:
        approval_id = f"apr_{uuid.uuid4().hex[:16]}"
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO approvals (approval_id, ts, scope_json, token_hash, granted_by,"
            " expires_ts, used) VALUES (?,?,?,?,?,?,0)",
            (approval_id, now.isoformat(timespec="seconds"),
             json.dumps(scope, ensure_ascii=False),
             hashlib.sha256(token.encode()).hexdigest(), granted_by, expires))
        self._conn.commit()
        return {"approval_id": approval_id, "token": token, "expires_ts": expires, "scope": scope}

    def consume_approval(self, token: str, semantic_id: str, action: str) -> str:
        token_hash = hashlib.sha256((token or "").encode()).hexdigest()
        row = self._conn.execute("SELECT * FROM approvals WHERE token_hash=?", (token_hash,)).fetchone()
        if not row:
            raise ApprovalError("unknown approval token")
        if row["used"]:
            raise ApprovalError("approval token already used")
        if row["expires_ts"] < utcnow():
            raise ApprovalError("approval token expired")
        scope = json.loads(row["scope_json"])
        if scope.get("semantic_id") not in (None, semantic_id) or scope.get("action") not in (None, action):
            raise ApprovalError("approval token scope mismatch")
        cur = self._conn.execute(
            "UPDATE approvals SET used=1 WHERE approval_id=? AND used=0", (row["approval_id"],))
        if cur.rowcount != 1:
            raise ApprovalError("approval token already used")
        self._conn.commit()
        return row["approval_id"]

    def pending_approvals(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE used=0 AND expires_ts>? ORDER BY ts DESC",
            (utcnow(),)).fetchall()
        return [{"approval_id": r["approval_id"], "ts": r["ts"],
                 "scope": json.loads(r["scope_json"]), "granted_by": r["granted_by"],
                 "expires_ts": r["expires_ts"]} for r in rows]

    def consume_scope(self, semantic_id: str, action: str) -> str:
        """Consume any pending approval that matches the requested scope (used for agent tasks)."""
        for item in self.pending_approvals():
            scope = item["scope"]
            if scope.get("semantic_id") in (None, semantic_id) and scope.get("action") in (None, action):
                cur = self._conn.execute(
                    "UPDATE approvals SET used=1 WHERE approval_id=? AND used=0",
                    (item["approval_id"],))
                if cur.rowcount == 1:
                    self._conn.commit()
                    return item["approval_id"]
        raise ApprovalError(f"no pending approval for {semantic_id}/{action}")

    # -- heal patches ---------------------------------------------------
    def review_heal_patch(self, patch_id: str, status: str, reviewed_by: str) -> None:
        if status not in ("approved", "rejected"):
            raise StoreError(f"invalid review status: {status}")
        cur = self._conn.execute(
            "UPDATE heal_patches SET status=?, reviewed_by=? WHERE patch_id=? AND status='pending'",
            (status, reviewed_by, patch_id))
        if cur.rowcount != 1:
            raise StoreError(f"patch {patch_id} not found or already reviewed")
        self._conn.commit()

    def list_heal_patches(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM heal_patches"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        rows = self._conn.execute(sql + " ORDER BY created_ts DESC", args).fetchall()
        return [{"patch_id": r["patch_id"], "semantic_id": r["semantic_id"], "app": r["app"],
                 "app_version": r["app_version"],
                 "proposed_chain": json.loads(r["proposed_chain_json"]),
                 "status": r["status"], "created_ts": r["created_ts"],
                 "reviewed_by": r["reviewed_by"]} for r in rows]

    def register_heal_patch(self, patch_id: str, semantic_id: str, app: str, app_version: str,
                            proposed_chain: list[dict], created_ts: str | None = None) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO heal_patches (patch_id, semantic_id, app, app_version,"
            " proposed_chain_json, status, created_ts) VALUES (?,?,?,?,?,'pending',?)",
            (patch_id, semantic_id, app, app_version,
             json.dumps(proposed_chain, ensure_ascii=False), created_ts or utcnow()))
        self._conn.commit()

    # -- windows --------------------------------------------------------
    def upsert_window(self, window_id: str, process_name: str, title: str,
                      geometry: list, whitelisted: bool = False) -> None:
        now = utcnow()
        self._conn.execute(
            "INSERT INTO windows (window_id, process_name, title, geometry_json, whitelisted,"
            " first_seen, last_seen) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(window_id) DO UPDATE SET title=excluded.title,"
            " geometry_json=excluded.geometry_json, last_seen=excluded.last_seen,"
            " whitelisted=MAX(windows.whitelisted, excluded.whitelisted)",
            (window_id, process_name, title, json.dumps(geometry), int(whitelisted), now, now))
        self._conn.commit()

    def whitelist_window(self, window_id: str) -> None:
        self._conn.execute("UPDATE windows SET whitelisted=1 WHERE window_id=?", (window_id,))
        self._conn.commit()

    def whitelisted_windows(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM windows WHERE whitelisted=1").fetchall()
        return [{"window_id": r["window_id"], "process_name": r["process_name"],
                 "title": r["title"], "bounds": json.loads(r["geometry_json"])} for r in rows]

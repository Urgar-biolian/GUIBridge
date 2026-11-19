"""SQLite event store: actions, state transitions, snapshot/screenshot evidence, approvals.

Append-only for events, snapshots and task_transitions (docs/sql.md). `verified` may only be
written by the independent verifier. Approval tokens are stored hashed and are single-use.

G1 merge note: the A-line modules (routed and integrated executors, the heal recorder, the live
adapter) name these same rows differently. Those names exist here as wrappers over the single
implementation below, and every wrapper keeps this file's gates — the `verified` actor check,
hashed single-use scoped tokens, and the windows foreign key. Nothing consumes an approval without
presenting the token a human was given.
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


class StoreError(RuntimeError):
    code = "unknown_state"


class ApprovalError(StoreError):
    """One approval failure type for both call shapes in the merged tree.

    The A-line raises `ApprovalError("no such token")`, the B-line raises
    `ApprovalError(code, message)`; the code is optional so neither call site has to know which
    lane wrote it.
    """

    code = "approval_required"

    def __init__(self, code: str, message: str | None = None):
        if message is None:
            code, message = self.code, code
        super().__init__(message)
        self.code = code
        self.message = message


def utcnow() -> str:
    """The store's single clock.

    Expiry and the A-line's `transition` timestamps read this function, so one patch moves every
    judgement at once; recorded rows keep the real time they were written at.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _scope_allows(scope: dict, window_id: str, semantic_id: str, action: str) -> bool:
    """A grant covers a request only if every scope field the grant named matches.

    The A-line writes a single-target scope as scalars (`semantic_id`, `action`), the B-line as
    lists (`semantic_ids`, `actions`); a scope that names no actionable dimension at all is not a
    grant for this action, so it matches nothing.
    """
    checks = []
    for key, value, scalar in (("window_id", window_id, True),
                               ("semantic_ids", semantic_id, False),
                               ("actions", action, False),
                               ("semantic_id", semantic_id, True),
                               ("action", action, True)):
        if key in scope:
            checks.append(scope[key] == value if scalar else value in (scope[key] or []))
    return bool(checks) and all(checks)


class _Serialized:
    """One connection shared across threads.

    The MCP SDK runs synchronous tools in a worker thread while the control plane writes from the
    event loop. `sqlite3` allows that with `check_same_thread=False`, but a composite write (row +
    audit event, grant + request) must not interleave with another thread's commit, hence the lock.
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
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
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

    def register_window(self, window_id: str, process_name: str, title: str, geometry,
                        whitelisted: bool | None = None) -> None:
        now = utcnow()
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
        cur = self.conn.execute("UPDATE windows SET whitelisted=? WHERE window_id=?",
                                (int(bool(allowed)), window_id))
        self.conn.commit()
        if cur.rowcount == 0:
            raise KeyError(window_id)

    def upsert_window(self, window_id: str, process_name: str, title: str, geometry,
                      whitelisted: bool = False) -> None:
        """The A-line name. Passing a title keeps a previously granted whitelist flag."""
        self.register_window(window_id, process_name, title, geometry, whitelisted=bool(whitelisted))

    def whitelist_window(self, window_id: str) -> None:
        self.set_whitelisted(window_id, True)

    def whitelisted_windows(self) -> list[dict]:
        return [{"window_id": w["window_id"], "process_name": w["process_name"], "title": w["title"],
                 "bounds": w["geometry"]} for w in self.list_windows(only_whitelisted=True)]

    @staticmethod
    def _window_row(r: sqlite3.Row) -> dict:
        return {"window_id": r["window_id"], "process_name": r["process_name"], "title": r["title"],
                "geometry": _load(r["geometry_json"]), "whitelisted": bool(r["whitelisted"]),
                "first_seen": r["first_seen"], "last_seen": r["last_seen"]}

    # snapshots

    def add_snapshot(self, window_id: str, elements, image_path: str | None = None) -> str:
        """Store an element summary; `elements` is a list of elements or a channel-shaped dict."""
        snapshot_id = "snap_" + _new_id()[:16]
        self.conn.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                          (snapshot_id, window_id, utcnow(), image_path, _dump(elements)))
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
        now = utcnow()
        self.conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                          (task_id, app, project_path, mode, "unknown",
                           _dump(acceptance) if acceptance else None, now, now))
        self.conn.commit()
        return {"task_id": task_id, "app": app, "project_path": project_path, "mode": mode,
                "state": "unknown", "acceptance": acceptance, "created_ts": now, "updated_ts": now}

    def get_task(self, task_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not r:
            return None
        return {"task_id": r["task_id"], "app": r["app"], "project_path": r["project_path"],
                "mode": r["mode"], "state": r["state"], "acceptance": _load(r["acceptance_json"]),
                "created_ts": r["created_ts"], "updated_ts": r["updated_ts"],
                "transitions": self.task_transitions(task_id)}

    def list_tasks(self, limit: int | None = None) -> list[dict]:
        """Oldest first, which is the order the timeline and the SSE replay read.

        `limit` keeps the most recent N and still returns them oldest first, so a caller that only
        wants the tail does not silently reverse the audit trail.
        """
        ids = [r["task_id"] for r in self.conn.execute("SELECT task_id FROM tasks ORDER BY created_ts")]
        if limit is not None:
            ids = ids[-limit:]
        return [t for t in (self.get_task(i) for i in ids) if t]

    def set_task_state(self, task_id: str, state: str, evidence_id: str, actor: str = "adapter") -> None:
        if state not in TASK_STATES:
            raise ValueError(f"unknown task state: {state}")
        if state == "verified" and actor != "verifier":
            raise PermissionError("verified may only be granted by the independent verifier (docs/sql.md)")
        now = utcnow()
        self.conn.execute("INSERT INTO task_transitions (task_id, state, evidence_id, ts) VALUES (?,?,?,?)",
                          (task_id, state, evidence_id, now))
        self.conn.execute("UPDATE tasks SET state=?, updated_ts=? WHERE task_id=?", (state, now, task_id))
        self.conn.commit()

    def transition(self, task_id: str, state: str, evidence_id: str = "") -> None:
        """The executor-facing name: it carries the executor actor, so `verified` stays unreachable."""
        self.set_task_state(task_id, state, evidence_id, actor="executor")

    def task_transitions(self, task_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT state, evidence_id, ts FROM task_transitions WHERE task_id=? ORDER BY id", (task_id,))
        return [{"state": r["state"], "evidence_id": r["evidence_id"], "ts": r["ts"]} for r in rows]

    # events

    def record(self, kind: str, payload: dict, evidence_paths: list[str] | None = None,
               task_id: str | None = None, window_id: str | None = None, semantic_id: str | None = None,
               action: str | None = None, approval_id: str | None = None,
               evidence: list[str] | None = None) -> str:
        event_id = "ev_" + _new_id()[:16]
        evidence_paths = evidence_paths if evidence_paths is not None else evidence
        if window_id is not None and not self.conn.execute(
                "SELECT 1 FROM windows WHERE window_id=?", (window_id,)).fetchone():
            # An approval or a heal event can name a window we observed but never registered. The
            # schema keeps windows as the identity table, so the id travels in the payload instead
            # of the foreign key rather than being dropped silently.
            payload = {**payload, "window_id_unregistered": window_id}
            window_id = None
        self.conn.execute(
            "INSERT INTO events (event_id, ts, kind, task_id, window_id, semantic_id, action, payload_json, "
            "evidence_json, approval_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, utcnow(), kind, task_id, window_id, semantic_id, action, _dump(payload),
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
        return [self._event_row(r) for r in self.conn.execute(sql, params)]

    def get_event(self, event_id: str) -> dict | None:
        r = self.conn.execute("SELECT rowid, * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._event_row(r) if r else None

    def latest_event(self, task_id: str, kind: str) -> dict | None:
        found = self.events(task_id=task_id, kind=kind, limit=1000)
        return found[-1] if found else None

    def events_after(self, event_id: str | None = None, limit: int = 200) -> list[dict]:
        anchor = self.get_event(event_id) if event_id else None
        return self.events(after_seq=(anchor or {}).get("seq", 0), limit=limit)

    @staticmethod
    def _event_row(r: sqlite3.Row) -> dict:
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

    def _grant(self, scope: dict, granted_by: str, ttl_seconds: int,
               request_id: str | None = None) -> tuple[str, str, str]:
        token = _new_id() + _new_id()
        now = datetime.now(timezone.utc)
        expires = _ts(now + timedelta(seconds=ttl_seconds))
        approval_id = "apv_" + _new_id()[:12]
        self.conn.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,0)",
                          (approval_id, _ts(now), _dump(scope), hash_token(token), granted_by, expires))
        self.conn.commit()
        self.record("approval_granted", {"approval_id": approval_id, "scope": scope,
                                        "request_id": request_id, "granted_by": granted_by,
                                        "expires_ts": expires},
                    window_id=scope.get("window_id"), approval_id=approval_id)
        return token, approval_id, expires

    def grant_approval(self, scope: dict, granted_by: str = "user", ttl_seconds: int = 600,
                       request_id: str | None = None) -> str:
        token, _, _ = self._grant(scope, granted_by, ttl_seconds, request_id)
        return token

    def create_approval(self, scope: dict, granted_by: str = "local-user",
                        ttl_seconds: int = 600) -> dict:
        """The A-line shape of a grant: the same scoped, hashed, single-use row, id included."""
        token, approval_id, expires = self._grant(scope, granted_by, ttl_seconds)
        return {"approval_id": approval_id, "token": token, "expires_ts": expires, "scope": scope}

    def consume_approval(self, token: str, window_id: str, semantic_id: str | None = None,
                         action: str | None = None, **scope) -> str:
        if action is None:
            # Legacy call shape from the perception lane: `consume(token, semantic_id, action)`.
            window_id, semantic_id, action = scope.get("window_id"), window_id, semantic_id
        row = self.conn.execute("SELECT * FROM approvals WHERE token_hash=? AND used=0",
                               (hash_token(token),)).fetchone()
        if row is None or row["expires_ts"] < utcnow():
            raise ApprovalError("approval_required", "no valid approval token for this action")
        granted = _load(row["scope_json"]) or {}
        if not _scope_allows(granted, window_id, semantic_id, action):
            raise ApprovalError("approval_required", "approval token does not cover this scope")
        self.conn.execute("UPDATE approvals SET used=1 WHERE approval_id=?", (row["approval_id"],))
        self.conn.commit()
        self.record("approval_consumed", {"approval_id": row["approval_id"], "window_id": window_id,
                                         "semantic_id": semantic_id, "action": action},
                    window_id=window_id, semantic_id=semantic_id, action=action,
                    approval_id=row["approval_id"])
        return row["approval_id"]

    def list_approvals(self) -> list[dict]:
        now = utcnow()
        return [{"approval_id": r["approval_id"], "ts": r["ts"], "scope": _load(r["scope_json"]),
                 "granted_by": r["granted_by"], "expires_ts": r["expires_ts"], "used": bool(r["used"]),
                 "expired": r["expires_ts"] < now}
                for r in self.conn.execute("SELECT * FROM approvals ORDER BY ts")]

    def pending_approvals(self) -> list[dict]:
        """Requests a human has not answered yet — derived from events, never from the token table."""
        granted = {e["payload"].get("request_id") for e in self.events(kind="approval_granted", limit=1000)}
        return [e for e in self.events(kind="approval_requested", limit=1000)
                if e["payload"].get("request_id") not in granted]

    # locator registry and heal patches

    def save_locator(self, semantic_id: str, app: str, app_version: str, chain, verification: str,
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
                 "chain": _load(r["chain_json"]), "verification": r["verification"],
                 "healed_at": r["healed_at"]}
                for r in self.conn.execute(sql + " ORDER BY semantic_id", params)]

    def _approved_patch(self, patch_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM heal_patches WHERE patch_id=?", (patch_id,)).fetchone()
        if row is None:
            raise KeyError(patch_id)
        if row["status"] != "approved":
            raise PermissionError(f"patch {patch_id} is not approved: {row['status']}")
        return {"patch_id": row["patch_id"], "semantic_id": row["semantic_id"], "app": row["app"],
                "app_version": row["app_version"], "proposed_chain": _load(row["proposed_chain_json"]),
                "status": row["status"], "created_ts": row["created_ts"], "reviewed_by": row["reviewed_by"]}

    def propose_heal_patch(self, semantic_id: str, app: str, app_version: str, proposed_chain) -> str:
        patch_id = "heal_" + _new_id()[:12]
        self.register_heal_patch(patch_id, semantic_id, app, app_version, proposed_chain)
        return patch_id

    def register_heal_patch(self, patch_id: str, semantic_id: str, app: str, app_version: str,
                            proposed_chain, created_ts: str | None = None) -> None:
        """Store a resolver-authored patch under its own id; review still runs through review_heal_patch."""
        self.conn.execute(
            "INSERT OR IGNORE INTO heal_patches (patch_id, semantic_id, app, app_version,"
            " proposed_chain_json, status, created_ts, reviewed_by) VALUES (?,?,?,?,?,'pending',?,NULL)",
            (patch_id, semantic_id, app, app_version, _dump(proposed_chain), created_ts or utcnow()))
        self.conn.commit()
        self.record("heal_proposed", {"patch_id": patch_id, "semantic_id": semantic_id,
                                      "app_version": app_version, "proposed_chain": proposed_chain},
                    semantic_id=semantic_id)

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
                              _load(patch["proposed_chain_json"]), "", utcnow())
        self.conn.commit()
        self.record("heal_reviewed", {"patch_id": patch_id, "semantic_id": patch["semantic_id"],
                                      "decision": decision, "reviewed_by": reviewed_by},
                    semantic_id=patch["semantic_id"])
        return {"patch_id": patch_id, "status": decision, "reviewed_by": reviewed_by}

    # retention

    def purge_expired(self) -> list[str]:
        """Full retention: expired events and snapshots go, and the caller gets their image paths."""
        cutoff = _ts(datetime.now(timezone.utc) - timedelta(days=self.retention_days))
        images = [r["image_path"] for r in self.conn.execute(
            "SELECT image_path FROM snapshots WHERE ts<? AND image_path IS NOT NULL", (cutoff,))
            if r["image_path"]]
        self.conn.execute("DELETE FROM events WHERE ts<?", (cutoff,))
        self.conn.execute("DELETE FROM snapshots WHERE ts<?", (cutoff,))
        self.conn.commit()
        return images

    def prune(self) -> int:
        """The narrower retention the perception lane calls: unbound events only, reported as a count."""
        cutoff = _ts(datetime.now(timezone.utc) - timedelta(days=self.retention_days))
        cur = self.conn.execute("DELETE FROM events WHERE ts<? AND task_id IS NULL", (cutoff,))
        self.conn.commit()
        return cur.rowcount

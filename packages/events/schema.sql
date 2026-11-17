-- GUIBridge v0.1 event store schema (SQLite)
-- Design notes: docs/sql.md. Evidence rows are append-only; never UPDATE events/snapshots.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS windows (
    window_id TEXT PRIMARY KEY,
    process_name TEXT NOT NULL,
    title TEXT NOT NULL,
    geometry_json TEXT NOT NULL,
    whitelisted INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    window_id TEXT NOT NULL REFERENCES windows(window_id),
    ts TEXT NOT NULL,
    image_path TEXT,
    elements_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    app TEXT NOT NULL,
    project_path TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'chat',
    state TEXT NOT NULL DEFAULT 'unknown',
    acceptance_json TEXT,
    created_ts TEXT NOT NULL,
    updated_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    state TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    expires_ts TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(task_id),
    window_id TEXT REFERENCES windows(window_id),
    semantic_id TEXT,
    action TEXT,
    payload_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    approval_id TEXT REFERENCES approvals(approval_id)
);

CREATE TABLE IF NOT EXISTS locators (
    semantic_id TEXT NOT NULL,
    app TEXT NOT NULL,
    app_version TEXT NOT NULL,
    chain_json TEXT NOT NULL,
    verification TEXT NOT NULL,
    healed_at TEXT,
    PRIMARY KEY (semantic_id, app, app_version)
);

CREATE TABLE IF NOT EXISTS heal_patches (
    patch_id TEXT PRIMARY KEY,
    semantic_id TEXT NOT NULL,
    app TEXT NOT NULL,
    app_version TEXT NOT NULL,
    proposed_chain_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_ts TEXT NOT NULL,
    reviewed_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_transitions_task ON task_transitions(task_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_window ON snapshots(window_id, ts);

INSERT OR IGNORE INTO schema_version(version, applied_ts) VALUES (1, datetime('now'));
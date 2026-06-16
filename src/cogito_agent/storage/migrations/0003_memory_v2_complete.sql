ALTER TABLE inbox ADD COLUMN trace_id TEXT;

CREATE TABLE IF NOT EXISTS daemon_state (
    id TEXT PRIMARY KEY DEFAULT 'main',
    status TEXT NOT NULL DEFAULT 'stopped',
    last_heartbeat TEXT,
    started_at TEXT,
    stopped_at TEXT,
    crash_marker TEXT,
    graceful_shutdown_marker TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory_edit_log (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    old_text TEXT NOT NULL,
    new_text TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT 'edit',
    actor_id TEXT NOT NULL DEFAULT 'cli',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inbox_items (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'system',
    priority TEXT NOT NULL DEFAULT 'normal',
    trace_id TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_inbox_items_workspace ON inbox_items(workspace_id);
CREATE INDEX IF NOT EXISTS idx_memory_edit_log_memory ON memory_edit_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_edit_log_workspace ON memory_edit_log(workspace_id);

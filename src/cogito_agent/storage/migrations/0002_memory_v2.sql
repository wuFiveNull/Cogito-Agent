ALTER TABLE memories ADD COLUMN pinned_at TEXT;
ALTER TABLE memories ADD COLUMN archived_at TEXT;

CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal',
    source TEXT NOT NULL DEFAULT 'system',
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_inbox_workspace ON inbox(workspace_id);

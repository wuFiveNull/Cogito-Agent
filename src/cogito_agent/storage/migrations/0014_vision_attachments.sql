-- Migration v14: Attachments, Vision Observations, Message-Attachment join

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT,
    content_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    original_filename TEXT NOT NULL DEFAULT '',
    storage_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_att_workspace ON attachments(workspace_id);
CREATE INDEX IF NOT EXISTS idx_att_session ON attachments(session_id);
CREATE INDEX IF NOT EXISTS idx_att_hash ON attachments(content_hash);
CREATE INDEX IF NOT EXISTS idx_att_ws_hash ON attachments(workspace_id, content_hash);

CREATE TABLE IF NOT EXISTS vision_observations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT,
    attachment_id TEXT NOT NULL,
    image_content_hash TEXT NOT NULL,
    prompt TEXT NOT NULL,
    normalized_prompt TEXT NOT NULL,
    result_text TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    preprocessing_version TEXT NOT NULL DEFAULT 'image-v1',
    cache_key TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vo_cache ON vision_observations(cache_key);
CREATE INDEX IF NOT EXISTS idx_vo_workspace ON vision_observations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_vo_attachment ON vision_observations(attachment_id);
CREATE INDEX IF NOT EXISTS idx_vo_created ON vision_observations(created_at);

CREATE TABLE IF NOT EXISTS message_attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (attachment_id) REFERENCES attachments(id),
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_ma_message ON message_attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_ma_attachment ON message_attachments(attachment_id);
CREATE INDEX IF NOT EXISTS idx_ma_workspace ON message_attachments(workspace_id);

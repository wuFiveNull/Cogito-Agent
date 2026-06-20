-- Migration v15: Meme Assets for frequently-used image memes

CREATE TABLE IF NOT EXISTS meme_assets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,

    name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    emotions_json TEXT NOT NULL DEFAULT '[]',
    use_cases_json TEXT NOT NULL DEFAULT '[]',
    avoid_cases_json TEXT NOT NULL DEFAULT '[]',
    text_on_image TEXT,

    source TEXT NOT NULL DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);

CREATE INDEX IF NOT EXISTS idx_meme_assets_workspace
    ON meme_assets(workspace_id);
CREATE INDEX IF NOT EXISTS idx_meme_assets_content_hash
    ON meme_assets(workspace_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_meme_assets_enabled
    ON meme_assets(workspace_id, enabled);

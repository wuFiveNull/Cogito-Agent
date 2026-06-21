CREATE TABLE IF NOT EXISTS memory_chunks (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    section TEXT DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mc_workspace ON memory_chunks(workspace_id);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
    text, content=memory_chunks, content_rowid=rowid
);

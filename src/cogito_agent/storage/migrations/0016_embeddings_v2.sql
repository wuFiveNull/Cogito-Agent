-- Migration v16: memory_embeddings_v2 with versioned, provider-aware embeddings
-- Preserves old memory_embeddings table for backward compatibility.

CREATE TABLE IF NOT EXISTS memory_embeddings_v2 (
    memory_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT '',
    provider_name TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    dimension INTEGER NOT NULL DEFAULT 0,
    embedding BLOB NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    embedding_version TEXT NOT NULL DEFAULT '2',
    status TEXT NOT NULL DEFAULT 'pending',
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (memory_id, provider_name, model_name, embedding_version),
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mev2_workspace ON memory_embeddings_v2(workspace_id);
CREATE INDEX IF NOT EXISTS idx_mev2_status ON memory_embeddings_v2(status);
CREATE INDEX IF NOT EXISTS idx_mev2_model ON memory_embeddings_v2(provider_name, model_name, embedding_version);
CREATE INDEX IF NOT EXISTS idx_mev2_content_hash ON memory_embeddings_v2(content_hash);

-- Migrate existing embeddings from v1 if they exist
INSERT OR IGNORE INTO memory_embeddings_v2
    (memory_id, workspace_id, provider_name, model_name, dimension,
     embedding, content_hash, embedding_version, status, created_at, updated_at)
SELECT
    me.memory_id,
    COALESCE(m.workspace_id, ''),
    'legacy',
    COALESCE(me.model_name, 'all-MiniLM-L6-v2'),
    384,
    me.embedding,
    '',
    '1',
    CASE WHEN me.embedding IS NOT NULL THEN 'ready' ELSE 'pending' END,
    COALESCE(me.updated_at, datetime('now')),
    COALESCE(me.updated_at, datetime('now'))
FROM memory_embeddings me
LEFT JOIN memories m ON me.memory_id = m.id
WHERE me.embedding IS NOT NULL AND me.embedding != '';

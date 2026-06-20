-- Migration v17: retrieval_traces for observability

CREATE TABLE IF NOT EXISTS retrieval_traces (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    gate_mode TEXT NOT NULL DEFAULT '',
    original_query TEXT NOT NULL DEFAULT '',
    enriched_query TEXT NOT NULL DEFAULT '',
    retrieval_mode TEXT NOT NULL DEFAULT '',
    degraded_reason TEXT NOT NULL DEFAULT '',
    sparse_candidate_count INTEGER NOT NULL DEFAULT 0,
    dense_candidate_count INTEGER NOT NULL DEFAULT 0,
    union_candidate_count INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    resident_count INTEGER NOT NULL DEFAULT 0,
    embedding_provider TEXT NOT NULL DEFAULT '',
    embedding_model TEXT NOT NULL DEFAULT '',
    embedding_dimension INTEGER NOT NULL DEFAULT 0,
    embedding_version TEXT NOT NULL DEFAULT '',
    sparse_latency_ms REAL NOT NULL DEFAULT 0.0,
    dense_latency_ms REAL NOT NULL DEFAULT 0.0,
    total_latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rt_workspace ON retrieval_traces(workspace_id);
CREATE INDEX IF NOT EXISTS idx_rt_created ON retrieval_traces(created_at);
CREATE INDEX IF NOT EXISTS idx_rt_mode ON retrieval_traces(retrieval_mode);

CREATE TABLE IF NOT EXISTS retrieval_trace_results (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    sparse_score REAL NOT NULL DEFAULT 0.0,
    dense_score REAL NOT NULL DEFAULT 0.0,
    recency_score REAL NOT NULL DEFAULT 0.0,
    confidence_score REAL NOT NULL DEFAULT 0.0,
    task_relevance_score REAL NOT NULL DEFAULT 0.0,
    type_priority_score REAL NOT NULL DEFAULT 0.0,
    final_score REAL NOT NULL DEFAULT 0.0,
    inclusion_reason TEXT NOT NULL DEFAULT '',
    excluded_reason TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (trace_id) REFERENCES retrieval_traces(id)
);

CREATE INDEX IF NOT EXISTS idx_rtr_trace ON retrieval_trace_results(trace_id);
CREATE INDEX IF NOT EXISTS idx_rtr_memory ON retrieval_trace_results(memory_id);

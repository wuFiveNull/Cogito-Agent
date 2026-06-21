CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    definition_id TEXT NOT NULL DEFAULT '',
    parent_run_id TEXT,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'normal',
    idempotency_key TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT,
    claimed_by TEXT,
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    input_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency
ON runs(run_type, idempotency_key)
WHERE idempotency_key <> '';
CREATE INDEX IF NOT EXISTS idx_runs_status_schedule ON runs(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_runs_definition ON runs(definition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, sequence);

CREATE TABLE IF NOT EXISTS run_outputs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    output_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_outputs_run ON run_outputs(run_id);

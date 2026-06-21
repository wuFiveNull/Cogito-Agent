CREATE TABLE IF NOT EXISTS autonomy_acks (
    ack_token_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reason_code TEXT NOT NULL DEFAULT '',
    error_redacted TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autonomy_acks_decision
    ON autonomy_acks(decision_id);

CREATE INDEX IF NOT EXISTS idx_autonomy_acks_status
    ON autonomy_acks(status, updated_at);

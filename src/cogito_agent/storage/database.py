from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1


def _load_migration_sql(name: str = "0001_initial.sql") -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "migrations", name)
    with open(path, encoding="utf-8") as f:
        return f.read()


_SCHEMA_SQL = _load_migration_sql()

_MIGRATIONS: dict[int, str] = {}


def register_migration(version: int, sql: str) -> None:
    _MIGRATIONS[version] = sql


register_migration(2, _load_migration_sql("0002_memory_v2.sql"))
register_migration(3, _load_migration_sql("0003_memory_v2_complete.sql"))
register_migration(
    4,
    """
    ALTER TABLE scheduled_jobs ADD COLUMN last_error TEXT;
    ALTER TABLE notifications ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
""",
)
register_migration(
    5,
    """
    ALTER TABLE skill_run_logs ADD COLUMN resume_data_json TEXT;
""",
)
register_migration(
    7,
    """
    ALTER TABLE outbox_messages ADD COLUMN delivery_attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE outbox_messages ADD COLUMN last_error TEXT;
    ALTER TABLE outbox_messages ADD COLUMN next_retry_at TEXT;
    ALTER TABLE outbox_messages ADD COLUMN delivered_at TEXT;
    ALTER TABLE outbox_messages ADD COLUMN read_at TEXT;
    ALTER TABLE outbox_messages ADD COLUMN dismissed_at TEXT;
    ALTER TABLE outbox_messages ADD COLUMN failed_at TEXT;
    ALTER TABLE outbox_messages ADD COLUMN updated_at TEXT;
    ALTER TABLE inbox_items ADD COLUMN decision_id TEXT DEFAULT '';
""",
)
register_migration(
    9,
    """
    CREATE TABLE IF NOT EXISTS workspace_roots (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        root_path TEXT NOT NULL,
        label TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        ignore_patterns TEXT DEFAULT '',
        max_file_size INTEGER DEFAULT 10485760,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_wr_workspace ON workspace_roots(workspace_id);
    CREATE TABLE IF NOT EXISTS workspace_files (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        root_id TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        file_name TEXT NOT NULL,
        mime_type TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0,
        sha256 TEXT DEFAULT '',
        modified_at TEXT,
        indexed_at TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        sensitivity_level TEXT DEFAULT 'normal',
        error_message TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (root_id) REFERENCES workspace_roots(id)
    );
    CREATE INDEX IF NOT EXISTS idx_wf_workspace ON workspace_files(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_wf_root ON workspace_files(root_id);
    CREATE INDEX IF NOT EXISTS idx_wf_status ON workspace_files(status);
    CREATE INDEX IF NOT EXISTS idx_wf_sha256 ON workspace_files(sha256);
    CREATE TABLE IF NOT EXISTS file_chunks (
        id TEXT PRIMARY KEY,
        workspace_file_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        token_count INTEGER DEFAULT 0,
        start_line INTEGER DEFAULT 0,
        end_line INTEGER DEFAULT 0,
        sha256 TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (workspace_file_id) REFERENCES workspace_files(id)
    );
    CREATE INDEX IF NOT EXISTS idx_fc_file ON file_chunks(workspace_file_id);
    CREATE INDEX IF NOT EXISTS idx_fc_workspace ON file_chunks(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_fc_chunk ON file_chunks(workspace_file_id, chunk_index);
    CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(
        text, content=file_chunks, content_rowid=rowid
    );
    CREATE TABLE IF NOT EXISTS file_chunk_embeddings (
        chunk_id TEXT NOT NULL,
        embedding BLOB,
        model_name TEXT DEFAULT '',
        PRIMARY KEY (chunk_id),
        FOREIGN KEY (chunk_id) REFERENCES file_chunks(id)
    );
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_id TEXT DEFAULT '',
        title TEXT NOT NULL,
        artifact_type TEXT NOT NULL DEFAULT 'markdown',
        mime_type TEXT DEFAULT 'text/markdown',
        content_json TEXT DEFAULT '',
        content_sha256 TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0,
        storage_path TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        trace_id TEXT DEFAULT '',
        audit_id TEXT DEFAULT '',
        deleted_at TEXT DEFAULT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_art_workspace ON artifacts(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_art_source ON artifacts(source_type, source_id);
    CREATE INDEX IF NOT EXISTS idx_art_trace ON artifacts(trace_id);
    CREATE INDEX IF NOT EXISTS idx_art_type ON artifacts(artifact_type);
""",
)
register_migration(11, _load_migration_sql("0011_approval_tool_call.sql"))
register_migration(
    12,
    """
    ALTER TABLE context_items ADD COLUMN freshness_score REAL NOT NULL DEFAULT 0.5;
    ALTER TABLE context_items ADD COLUMN trust_score REAL NOT NULL DEFAULT 0.5;
    ALTER TABLE context_items ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE context_items ADD COLUMN stable_ref TEXT NOT NULL DEFAULT '';
    ALTER TABLE context_items ADD COLUMN exclusion_reason TEXT NOT NULL DEFAULT '';
    CREATE INDEX IF NOT EXISTS idx_context_stable_ref ON context_items(stable_ref);
""",
)
register_migration(
    13,
    """
    CREATE TABLE IF NOT EXISTS session_summaries (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        parent_summary_id TEXT,
        strategy TEXT NOT NULL,
        summary TEXT NOT NULL,
        source_message_count INTEGER NOT NULL,
        through_message_id TEXT NOT NULL,
        derived INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_summary_id) REFERENCES session_summaries(id),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_summary_session
        ON session_summaries(workspace_id, session_id, created_at);
""",
)
register_migration(14, _load_migration_sql("0014_vision_attachments.sql"))
register_migration(15, _load_migration_sql("0015_meme_assets.sql"))
register_migration(16, _load_migration_sql("0016_embeddings_v2.sql"))
register_migration(17, _load_migration_sql("0017_retrieval_traces.sql"))
register_migration(18, _load_migration_sql("0018_mcp_trust.sql"))
register_migration(19, _load_migration_sql("0019_durable_runs.sql"))
register_migration(20, _load_migration_sql("0020_autonomy_acks.sql"))
register_migration(21, _load_migration_sql("0021_memory_chunks_fts.sql"))
register_migration(22, _load_migration_sql("0022_cleanup_old_memory_tables.sql"))
register_migration(23, _load_migration_sql("0023_cleanup_memory_edit_log.sql"))
register_migration(24, _load_migration_sql("0024_cleanup_memory_candidates.sql"))
register_migration(
    25,
    """
    CREATE TABLE IF NOT EXISTS memory_items (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        reinforcement INTEGER NOT NULL DEFAULT 1,
        emotional_weight INTEGER NOT NULL DEFAULT 0,
        extra_json TEXT NOT NULL DEFAULT '{}',
        source_ref TEXT NOT NULL DEFAULT '',
        happened_at TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_items_hash
        ON memory_items (workspace_id, content_hash, memory_type);
    CREATE INDEX IF NOT EXISTS idx_memory_items_type
        ON memory_items (workspace_id, memory_type);
    CREATE INDEX IF NOT EXISTS idx_memory_items_time
        ON memory_items (workspace_id, happened_at);
    """,
)

register_migration(26,
    """
    CREATE TABLE IF NOT EXISTS input_queue (
        id           TEXT PRIMARY KEY,
        channel      TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        session_id   TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'processing', 'done', 'failed')),
        task_type    TEXT NOT NULL DEFAULT 'user_message',
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        started_at   TEXT,
        done_at      TEXT,
        error        TEXT,
        retry_count  INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_iq_status ON input_queue(status);
    CREATE INDEX IF NOT EXISTS idx_iq_created ON input_queue(created_at);
    CREATE INDEX IF NOT EXISTS idx_iq_workspace ON input_queue(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_iq_task_type ON input_queue(task_type);
    """,
)

register_migration(
    10,
    """
    CREATE TABLE IF NOT EXISTS drift_runs (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        trace_id TEXT DEFAULT '',
        audit_id TEXT DEFAULT '',
        artifact_id TEXT DEFAULT '',
        started_at TEXT,
        completed_at TEXT,
        error_message TEXT DEFAULT '',
        metadata_json TEXT DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_drift_workspace ON drift_runs(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_drift_status ON drift_runs(status);
    CREATE INDEX IF NOT EXISTS idx_drift_skill ON drift_runs(skill_name);
    CREATE TABLE IF NOT EXISTS drift_state (
        id TEXT PRIMARY KEY DEFAULT 'main',
        enabled INTEGER NOT NULL DEFAULT 1,
        paused INTEGER NOT NULL DEFAULT 0,
        quiet_hours_start TEXT DEFAULT '',
        quiet_hours_end TEXT DEFAULT '',
        daily_budget INTEGER NOT NULL DEFAULT 5,
        timezone TEXT NOT NULL DEFAULT 'UTC',
        last_tick_at TEXT,
        runs_today INTEGER NOT NULL DEFAULT 0,
        pause_reason TEXT DEFAULT '',
        paused_at TEXT,
        last_user_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO drift_state (id) VALUES ('main');
""",
)
register_migration(
    6,
    """
    CREATE TABLE IF NOT EXISTS notification_decisions (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL DEFAULT '*',
        user_id TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        reason_code TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        cost_score REAL NOT NULL DEFAULT 0.0,
        priority_score REAL NOT NULL DEFAULT 0.0,
        dedup_hit INTEGER NOT NULL DEFAULT 0,
        quiet_hours_hit INTEGER NOT NULL DEFAULT 0,
        quota_hit INTEGER NOT NULL DEFAULT 0,
        requires_approval INTEGER NOT NULL DEFAULT 0,
        trace_id TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_nd_workspace ON notification_decisions(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_nd_created ON notification_decisions(created_at);
    CREATE INDEX IF NOT EXISTS idx_nd_event ON notification_decisions(event_id);
    CREATE TABLE IF NOT EXISTS outbox_messages (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL DEFAULT '*',
        user_id TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        priority TEXT NOT NULL DEFAULT 'normal',
        source TEXT NOT NULL DEFAULT 'system',
        trace_id TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_om_workspace ON outbox_messages(workspace_id);
    CREATE INDEX IF NOT EXISTS idx_om_status ON outbox_messages(status);
    CREATE TABLE IF NOT EXISTS feedback_entries (
        id TEXT PRIMARY KEY,
        decision_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL DEFAULT '*',
        user_id TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        trace_id TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_fe_decision ON feedback_entries(decision_id);
    CREATE INDEX IF NOT EXISTS idx_fe_workspace ON feedback_entries(workspace_id);
""",
)


class Database:
    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

    def initialize(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def create_runtime_services(
        self,
        *,
        capability_registry: Any = None,
        policy_engine: Any = None,
        artifact_writer: Any = None,
    ) -> Any:
        """Compose SQLite-backed runtime ports outside the runtime package.

        Application composition roots use this adapter to bind concrete local
        services to the provider-neutral runtime ports.
        """
        from cogito_agent.execution import (
            GovernedCapabilityExecutor,
            default_guardians,
        )
        from cogito_agent.governance import AuditLogger, PolicyEngine
        from cogito_agent.runtime.ports import RuntimeServices
        from cogito_agent.storage.repositories import ApprovalRepository
        from cogito_agent.storage.runtime_persistence import SqliteRuntimePersistence
        from cogito_agent.trace import Tracer

        policy = policy_engine or PolicyEngine()
        tracer = Tracer(self)
        audit = AuditLogger(self)
        executor = None
        tool_schema_provider = None
        if capability_registry is not None:
            executor = GovernedCapabilityExecutor(
                capability_registry,
                policy,
                approvals=ApprovalRepository(self),
                audit=audit,
                tracer=tracer,
                guardians=default_guardians(),
                artifact_writer=artifact_writer,
            )
            # ToolSchemaProvider adapter — keeps capability.schemas out of runtime
            class _CapToolSchemaProvider:
                def __init__(self, cap_reg):
                    self._cap_reg = cap_reg
                def get_tool_schemas(self, actor="assistant"):
                    from cogito_agent.capability.schemas import filter_available_tools, manifest_to_tool_schema
                    manifests = self._cap_reg.list_tools()
                    available = filter_available_tools(manifests, actor=actor)
                    return [manifest_to_tool_schema(m) for m in available]
            tool_schema_provider = _CapToolSchemaProvider(capability_registry)
        return RuntimeServices(
            persistence=SqliteRuntimePersistence(self),
            tracer=tracer,
            audit=audit,
            policy=policy,
            capability_catalog=capability_registry,
            capability_executor=executor,
            tool_schema_provider=tool_schema_provider,
        )

    def create_subagent_persistence(self) -> Any:
        from cogito_agent.storage.subagent_persistence import (
            SqliteSubagentPersistence,
        )

        return SqliteSubagentPersistence(self)

    def create_run_repository(self) -> Any:
        from cogito_agent.runs import RunRepository

        return RunRepository(self)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def current_version(self) -> int:
        cur = self._conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def backup_to(self, destination: str) -> str:
        """Create a transactionally consistent SQLite backup."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_conn = sqlite3.connect(str(target))
        try:
            self._conn.backup(backup_conn)
        finally:
            backup_conn.close()
        return str(target)

    def quick_check(self) -> tuple[bool, str]:
        row = self._conn.execute("PRAGMA quick_check").fetchone()
        message = str(row[0]) if row else "quick_check returned no result"
        return message == "ok", message

    def maintain(self, *, auto_vacuum: bool = False) -> dict[str, Any]:
        """Run safe SQLite maintenance and return an auditable result."""
        ok, message = self.quick_check()
        result: dict[str, Any] = {
            "integrity_ok": ok,
            "integrity_message": message,
            "wal_checkpoint": None,
            "optimized": False,
            "vacuumed": False,
        }
        if not ok:
            return result
        checkpoint = self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        result["wal_checkpoint"] = tuple(checkpoint) if checkpoint else None
        self._conn.execute("PRAGMA optimize")
        result["optimized"] = True
        if auto_vacuum:
            self._conn.execute("PRAGMA auto_vacuum=FULL")
            self._conn.execute("VACUUM")
            result["vacuumed"] = True
        self._conn.commit()
        return result

    def _backup_before_migration(self, current: int, target: int) -> str | None:
        if self._path == ":memory:" or not Path(self._path).exists():
            return None
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = f"{self._path}.pre-migrate.v{current}-to-v{target}.{timestamp}.bak"
        return self.backup_to(backup_path)

    def migrate(self) -> list[int]:
        applied: list[int] = []
        current = self.current_version()
        pending = sorted(v for v in _MIGRATIONS if v > current)
        if pending:
            self._backup_before_migration(current, pending[-1])
        for version in pending:
            sql = _MIGRATIONS[version]
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,),
            )
            self._conn.commit()
            applied.append(version)
        return applied

    def export_workspace(self, workspace_id: str) -> dict[str, Any]:
        data: dict[str, Any] = {"workspace_id": workspace_id}
        tables = [
            "sessions",
            "messages",
            "memories",
            "file_artifacts",
            "traces",
            "spans",
            "tool_calls",
            "model_calls",
            "audit_logs",
            "source_lineage",
            "context_items",
            "approval_records",
            "workspace_settings",
            "scheduled_jobs",
            "notifications",
            "workspace_skills",
            "skill_run_logs",
            "inbox_items",
            "inbox",
            "daemon_state",
            "workspace_roots",
            "workspace_files",
            "file_chunks",
            "file_chunk_embeddings",
            "artifacts",
            "drift_runs",
            "attachments",
            "vision_observations",
            "message_attachments",
        ]
        for table in tables:
            try:
                cur = self._conn.execute(
                    f"SELECT * FROM {table} WHERE workspace_id = ?",  # noqa: S608
                    (workspace_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                if rows:
                    data[table] = rows
            except Exception:
                pass
        cur = self._conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        ws_row = cur.fetchone()
        if ws_row:
            data["workspace"] = dict(ws_row)
        return data

    @staticmethod
    def quick_check(path: str) -> str | None:
        """Run PRAGMA quick_check on a database file. Returns None if OK, error string if not."""
        import sqlite3
        try:
            conn = sqlite3.connect(path)
            result = conn.execute("PRAGMA quick_check").fetchone()
            conn.close()
        except sqlite3.Error as exc:
            return str(exc)
        if result is None or result[0] != "ok":
            return str(result[0] if result else "quick_check returned no result")
        return None

    @staticmethod
    def export_table_json(path: str, table: str, order_by: str = "") -> list[dict[str, object]]:
        """Export all rows from a table as a list of dicts. Uses a standalone connection."""
        import sqlite3
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            sql = f"SELECT * FROM {table}"
            if order_by:
                sql += f" ORDER BY {order_by}"
            rows = conn.execute(sql).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def delete_all_secrets(path: str) -> None:
        """Delete all rows from the secrets table (for redacted backup)."""
        import sqlite3
        try:
            conn = sqlite3.connect(path)
            conn.execute("DELETE FROM secrets")
            conn.commit()
            conn.close()
        except Exception:
            pass

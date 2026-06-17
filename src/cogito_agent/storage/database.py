from __future__ import annotations

import os
import sqlite3
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
register_migration(4, """
    ALTER TABLE scheduled_jobs ADD COLUMN last_error TEXT;
    ALTER TABLE notifications ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
""")
register_migration(5, """
    ALTER TABLE skill_run_logs ADD COLUMN resume_data_json TEXT;
""")
register_migration(6, """
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
""")


class Database:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def current_version(self) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def migrate(self) -> list[int]:
        applied: list[int] = []
        current = self.current_version()
        pending = sorted(v for v in _MIGRATIONS if v > current)
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
            "sessions", "messages", "memories",
            "file_artifacts", "memory_candidates", "traces", "spans",
            "tool_calls", "model_calls", "audit_logs", "source_lineage",
            "context_items", "approval_records", "workspace_settings",
            "scheduled_jobs", "notifications",
            "workspace_skills", "skill_run_logs",
            "inbox_items", "inbox", "memory_edit_log",
            "daemon_state",
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
        cur = self._conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        )
        ws_row = cur.fetchone()
        if ws_row:
            data["workspace"] = dict(ws_row)
        return data

from __future__ import annotations

import os
import sqlite3
from typing import Any

_SCHEMA_VERSION = 1


def _load_migration_sql() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "migrations", "0001_initial.sql")
    with open(path, encoding="utf-8") as f:
        return f.read()


_SCHEMA_SQL = _load_migration_sql()

_MIGRATIONS: dict[int, str] = {}


def register_migration(version: int, sql: str) -> None:
    _MIGRATIONS[version] = sql


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

"""PresenceStore — unified user activity awareness.

All subsystems (DriftRuntime, NotificationGate, ContextEngine) use this
single source of truth to answer: "Is the user active right now?"
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_PRESENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS presence (
    session_key TEXT PRIMARY KEY,
    last_user_at TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'unknown',
    extra_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class PresenceStore:
    """Tracks user activity across sessions/channels.

    Lightweight store — one row per session_key, updated on every user
    interaction. Designed to be called from every user message entry point
    (CLI, API, Console, daemon).
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            self._db.connection.executescript(_PRESENCE_SCHEMA)
            self._db.connection.commit()
        except Exception:
            logger.exception("Failed to create presence table")

    def touch(
        self,
        session_key: str = "default",
        *,
        channel: str = "unknown",
        now: datetime | None = None,
    ) -> None:
        """Record user activity now."""
        now_iso = (now or datetime.now(UTC)).isoformat()
        try:
            self._db.connection.execute(
                "INSERT INTO presence (session_key, last_user_at, channel, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_key) DO UPDATE SET"
                " last_user_at=excluded.last_user_at,"
                " channel=excluded.channel,"
                " updated_at=excluded.updated_at",
                (session_key, now_iso, channel, now_iso),
            )
            self._db.connection.commit()
        except Exception:
            logger.exception("Failed to touch presence")

    def get_last_user_at(self, session_key: str = "default") -> datetime | None:
        """Return the last user activity time, or None if never seen."""
        try:
            row = self._db.connection.execute(
                "SELECT last_user_at FROM presence WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            if row and row["last_user_at"]:
                return datetime.fromisoformat(str(row["last_user_at"]))
        except Exception:
            logger.exception("Failed to read presence")
        return None

    def is_online(
        self,
        session_key: str = "default",
        *,
        timeout_minutes: int = 5,
        now: datetime | None = None,
    ) -> bool:
        """User active within *timeout_minutes* → online."""
        last = self.get_last_user_at(session_key)
        if last is None:
            return False
        return (now or datetime.now(UTC)) - last < timedelta(minutes=timeout_minutes)

    def get_idle_minutes(self, session_key: str = "default") -> float:
        """Minutes since last user activity. Returns 0.0 if never seen."""
        last = self.get_last_user_at(session_key)
        if last is None:
            return 0.0
        return max(0.0, (datetime.now(UTC) - last).total_seconds() / 60.0)

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all tracked sessions (for admin/debug)."""
        try:
            rows = self._db.connection.execute(
                "SELECT * FROM presence ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Protocol

from cogito_agent.storage import Database


class SummaryStrategy(Protocol):
    name: str

    def summarize(self, previous_summary: str, messages: list[dict[str, object]]) -> str: ...


class DeterministicSummaryStrategy:
    name = "deterministic-v1"

    def __init__(self, max_chars: int = 2000) -> None:
        self._max_chars = max(100, max_chars)

    def summarize(self, previous_summary: str, messages: list[dict[str, object]]) -> str:
        parts = [previous_summary.strip()] if previous_summary.strip() else []
        for message in messages:
            role = str(message.get("role", "unknown"))
            content = " ".join(str(message.get("content", "")).split())
            if content:
                parts.append(f"{role}: {content}")
        combined = "\n".join(parts)
        if len(combined) <= self._max_chars:
            return combined
        return "…" + combined[-(self._max_chars - 1) :]


@dataclass(frozen=True)
class CompressionPolicy:
    min_new_messages: int = 8
    min_new_characters: int = 4000

    def should_compress(self, messages: list[dict[str, object]]) -> bool:
        if len(messages) >= self.min_new_messages:
            return True
        return sum(len(str(item.get("content", ""))) for item in messages) >= (
            self.min_new_characters
        )


class SessionCompressionService:
    """Create immutable derived summaries without modifying source messages."""

    def __init__(
        self,
        db: Database,
        strategy: SummaryStrategy | None = None,
        policy: CompressionPolicy | None = None,
    ) -> None:
        self._db = db
        self._strategy = strategy or DeterministicSummaryStrategy()
        self._policy = policy or CompressionPolicy()

    def update_summary(
        self, workspace_id: str, session_id: str, *, force: bool = False
    ) -> dict[str, object] | None:
        previous = self.get_latest(workspace_id, session_id)
        previous_id = str(previous["id"]) if previous else ""
        through_id = str(previous["through_message_id"]) if previous else ""
        messages = self._messages_after(workspace_id, session_id, through_id)
        if not messages or (not force and not self._policy.should_compress(messages)):
            return None
        previous_text = str(previous["summary"]) if previous else ""
        summary = self._strategy.summarize(previous_text, messages)
        summary_id = str(uuid.uuid4())
        through_message_id = str(messages[-1]["id"])
        self._db.connection.execute(
            "INSERT INTO session_summaries"
            " (id, workspace_id, session_id, parent_summary_id, strategy, summary,"
            " source_message_count, through_message_id, derived)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                summary_id,
                workspace_id,
                session_id,
                previous_id or None,
                self._strategy.name,
                summary,
                len(messages),
                through_message_id,
            ),
        )
        self._db.connection.commit()
        return self.get_by_id(summary_id)

    def get_latest(self, workspace_id: str, session_id: str) -> dict[str, object] | None:
        try:
            row = self._db.connection.execute(
                "SELECT * FROM session_summaries"
                " WHERE workspace_id = ? AND session_id = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (workspace_id, session_id),
            ).fetchone()
        except sqlite3.Error:
            return None
        return dict(row) if row else None

    def get_by_id(self, summary_id: str) -> dict[str, object] | None:
        try:
            row = self._db.connection.execute(
                "SELECT * FROM session_summaries WHERE id = ?", (summary_id,)
            ).fetchone()
        except sqlite3.Error:
            return None
        return dict(row) if row else None

    def _messages_after(
        self, workspace_id: str, session_id: str, through_message_id: str
    ) -> list[dict[str, object]]:
        after_rowid = 0
        if through_message_id:
            row = self._db.connection.execute(
                "SELECT rowid FROM messages WHERE id = ? AND workspace_id = ? AND session_id = ?",
                (through_message_id, workspace_id, session_id),
            ).fetchone()
            after_rowid = int(row[0]) if row else 0
        rows = self._db.connection.execute(
            "SELECT id, role, content, created_at FROM messages"
            " WHERE workspace_id = ? AND session_id = ? AND rowid > ?"
            " ORDER BY rowid",
            (workspace_id, session_id, after_rowid),
        ).fetchall()
        return [dict(row) for row in rows]

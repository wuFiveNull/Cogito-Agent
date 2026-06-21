from __future__ import annotations

from .database import Database
from .repositories import MessageRepository, SessionRepository


class SqliteSubagentPersistence:
    def __init__(self, db: Database) -> None:
        self._sessions = SessionRepository(db)
        self._messages = MessageRepository(db)

    def create_session(
        self,
        session_id: str,
        workspace_id: str,
        title: str,
    ) -> None:
        self._sessions.create(session_id, workspace_id, title)

    def create_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        self._messages.create(
            mid=message_id,
            workspace_id=workspace_id,
            session_id=session_id,
            role=role,
            content=content,
        )

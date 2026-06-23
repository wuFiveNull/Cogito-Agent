from __future__ import annotations

import json
import uuid

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MessageRepository, SessionRepository


class SessionApplicationService:
    def __init__(self, db: Database, audit: AuditLogger | None = None) -> None:
        self._db = db
        self._sessions = SessionRepository(db)
        self._messages = MessageRepository(db)
        self._audit = audit or AuditLogger(db)

    def list(self, workspace_id: str) -> list[dict[str, object]]:
        """List all active sessions for a workspace."""
        return self._sessions.list_by_workspace(workspace_id)

    def create(
        self,
        workspace_id: str,
        title: str = "New Chat",
        *,
        actor_id: str = "user",
    ) -> dict[str, object]:
        session_id = str(uuid.uuid4())
        result = self._sessions.create(session_id, workspace_id, title)
        self._log(actor_id, "session_created", workspace_id, session_id)
        return result

    def rename(
        self,
        workspace_id: str,
        session_id: str,
        title: str,
        *,
        actor_id: str = "user",
    ) -> dict[str, object] | None:
        session = self._sessions.get_by_id(session_id, workspace_id)
        clean_title = " ".join(title.split())[:80]
        if session is None or not clean_title:
            return None
        self._sessions.update(session_id, workspace_id, title=clean_title)
        self._log(
            actor_id,
            "session_renamed",
            workspace_id,
            session_id,
            {"before": session.get("title", ""), "after": clean_title},
        )
        return self._sessions.get_by_id(session_id, workspace_id)

    def branch(
        self,
        workspace_id: str,
        session_id: str,
        *,
        actor_id: str = "user",
    ) -> dict[str, object] | None:
        source = self._sessions.get_by_id(session_id, workspace_id)
        if source is None:
            return None
        branch_id = str(uuid.uuid4())
        source_title = str(source.get("title", "Chat")) or "Chat"
        branch = self._sessions.create(
            branch_id,
            workspace_id,
            f"{source_title[:67]} - branch",
        )
        for message in self._messages.list_by_session(session_id, workspace_id):
            self._messages.create(
                str(uuid.uuid4()),
                workspace_id,
                branch_id,
                str(message.get("role", "assistant")),
                str(message.get("content", "")),
                str(message.get("metadata_json", "{}")),
            )
        self._log(
            actor_id,
            "session_branched",
            workspace_id,
            branch_id,
            {"source_session_id": session_id},
        )
        return branch

    def archive(
        self,
        workspace_id: str,
        session_id: str,
        *,
        actor_id: str = "user",
    ) -> bool:
        if self._sessions.get_by_id(session_id, workspace_id) is None:
            return False
        self._sessions.soft_delete(session_id, workspace_id)
        self._log(actor_id, "session_archived", workspace_id, session_id)
        return True

    def delete(
        self,
        workspace_id: str,
        session_id: str,
        *,
        actor_id: str = "user",
    ) -> bool:
        if self._sessions.get_by_id(session_id, workspace_id) is None:
            return False
        self._sessions.hard_delete(session_id, workspace_id)
        self._log(actor_id, "session_deleted", workspace_id, session_id)
        return True

    def _log(
        self,
        actor_id: str,
        action: str,
        workspace_id: str,
        session_id: str,
        details: dict[str, object] | None = None,
    ) -> None:
        self._audit.log(
            actor_id=actor_id,
            action=action,
            resource="session",
            workspace_id=workspace_id,
            session_id=session_id,
            decision="allow",
            reason="session management",
            details=json.dumps(details or {}),
        )

from __future__ import annotations

from cogito_agent.storage import Database


class AuditLogger:
    def __init__(self, db: Database) -> None:
        self._db = db

    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
    ) -> None:
        self._db.connection.execute(
            "INSERT INTO audit_logs"
            " (actor_id, action, resource, workspace_id, session_id,"
            " trace_id, decision, reason, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                actor_id, action, resource, workspace_id, session_id,
                trace_id, decision, reason, details,
            ),
        )
        self._db.connection.commit()

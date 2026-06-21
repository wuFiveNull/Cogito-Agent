from __future__ import annotations

import re

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
        redact_details: bool = True,
    ) -> str:
        from cogito_agent.trace.redaction import RedactionHelper

        helper = RedactionHelper()
        actor_id = helper.redact(actor_id)
        action = helper.redact(action)
        # ``secret:<key-name>`` is a structured resource identifier, not a
        # secret value. Preserve safe key names so audit records remain
        # queryable; all other resource strings still pass through redaction.
        if not re.fullmatch(r"secret:[A-Za-z0-9_.-]+", resource):
            resource = helper.redact(resource)
        decision = helper.redact(decision)
        reason = helper.redact(reason)
        if redact_details and details and details != "{}":
            details = helper.redact(details)
        import uuid

        audit_id = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO audit_logs"
            " (id, actor_id, action, resource, workspace_id, session_id,"
            " trace_id, decision, reason, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                actor_id,
                action,
                resource,
                workspace_id,
                session_id,
                trace_id,
                decision,
                reason,
                details,
            ),
        )
        self._db.connection.commit()
        return audit_id

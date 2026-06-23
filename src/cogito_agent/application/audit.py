from __future__ import annotations

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.storage import Database


def log_audit(
    db: Database,
    actor_id: str,
    action: str,
    resource: str,
    workspace_id: str,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    decision: str = "allow",
    reason: str = "",
    details: str = "{}",
    redact_details: bool = True,
) -> str:
    """Write an audit log entry without importing AuditLogger directly.

    This is a thin wrapper around ``AuditLogger`` that lets Console and CLI
    views write audit records without depending on the ``governance`` package.
    """
    return AuditLogger(db).log(
        actor_id=actor_id,
        action=action,
        resource=resource,
        workspace_id=workspace_id,
        session_id=session_id,
        trace_id=trace_id,
        decision=decision,
        reason=reason,
        details=details,
        redact_details=redact_details,
    )

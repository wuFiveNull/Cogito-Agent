from __future__ import annotations

from cogito_agent.governance import AuditLogger
from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


def test_tracer_redacts_without_caller_supplied_tokens() -> None:
    db = Database()
    db.initialize()
    tracer = Tracer(db)
    trace = tracer.create_trace("workspace", "event")
    span = tracer.create_span(trace.id, "call", SpanKind.runtime)
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    tracer.log_model_call(
        trace.id,
        span.id,
        prompt_summary=f"token={secret}",
        response_summary=f"Bearer {secret}",
        error=f"api_key={secret}",
    )
    row = db.connection.execute(
        "SELECT prompt_summary, response_summary, error FROM model_calls"
    ).fetchone()
    assert secret not in " ".join(str(value) for value in row)
    db.close()


def test_audit_redacts_all_free_text_fields() -> None:
    db = Database()
    db.initialize()
    secret = "sk-audit-abcdefghijklmnopqrstuvwxyz"

    audit_id = AuditLogger(db).log(
        actor_id=f"actor:{secret}",
        action="test.audit",
        resource=f"resource:{secret}",
        workspace_id="workspace",
        decision=f"deny:{secret}",
        reason=f"failed with {secret}",
        details=f'{{"error":"{secret}"}}',
    )

    row = db.connection.execute(
        "SELECT actor_id, resource, decision, reason, details FROM audit_logs WHERE id=?",
        (audit_id,),
    ).fetchone()
    assert row is not None
    assert secret not in " ".join(str(value) for value in row)
    db.close()

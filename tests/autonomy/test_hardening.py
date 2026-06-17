"""Tests for SpanKind, migration, and redaction in autonomy context."""

import pytest

from cogito_agent.autonomy import ProactiveLoop
from cogito_agent.autonomy.events import AutonomyEvent
from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import RedactionHelper, Tracer


def test_spankind_autonomous_exists():
    assert hasattr(SpanKind, "autonomous")
    assert SpanKind.autonomous == "autonomous"


def test_proactive_loop_uses_autonomous_kind(
    db, wid: str, proactive_loop: ProactiveLoop,
):
    event = AutonomyEvent(title="span kind test", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    assert decision.trace_id
    cur = db.connection.execute(
        "SELECT kind FROM spans WHERE trace_id = ?",
        (decision.trace_id,),
    )
    rows = cur.fetchall()
    kinds = [r["kind"] for r in rows]
    assert "autonomous" in kinds


def test_migration_v6_idempotent():
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    # run migration again
    applied = db.migrate()
    assert applied == []
    # verify tables exist
    cur = db.connection.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type='table' AND name IN"
        " ('notification_decisions', 'outbox_messages', 'feedback_entries')"
    )
    tables = {r["name"] for r in cur.fetchall()}
    assert "notification_decisions" in tables
    assert "outbox_messages" in tables
    assert "feedback_entries" in tables
    db.close()


def test_redaction_in_autonomy_output():
    helper = RedactionHelper()
    sensitive = "api_key: secret-12345"
    redacted = helper.redact(sensitive)
    assert "secret-12345" not in redacted
    assert "[REDACTED]" in redacted or "****" in redacted


def test_autonomy_event_title_no_secret_leak_in_audit(
    db, wid: str, proactive_loop: ProactiveLoop,
):
    event = AutonomyEvent(title="test with api_key=sk-123", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    assert decision.trace_id
    # Check that audit logs don't contain the raw secret
    cur = db.connection.execute(
        "SELECT details FROM audit_logs WHERE trace_id = ?",
        (decision.trace_id,),
    )
    rows = cur.fetchall()
    for row in rows:
        assert "sk-123" not in (row["details"] or "")

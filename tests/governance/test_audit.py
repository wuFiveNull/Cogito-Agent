from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database


def test_audit_log(db: Database) -> None:
    logger = AuditLogger(db)
    logger.log(
        actor_id="assistant",
        action="file_read",
        resource="workspace_file:/tmp/test.txt",
        workspace_id="ws-1",
        session_id="sess-1",
        trace_id="trace-1",
        decision="allow_with_audit",
    )
    cur = db.connection.execute("SELECT * FROM audit_logs")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "assistant"
    assert rows[0]["action"] == "file_read"


def test_audit_log_defaults(db: Database) -> None:
    logger = AuditLogger(db)
    logger.log(
        actor_id="user",
        action="login",
        resource="session",
        workspace_id="ws-1",
    )
    cur = db.connection.execute("SELECT * FROM audit_logs")
    row = cur.fetchone()
    assert row is not None
    assert row["decision"] == ""

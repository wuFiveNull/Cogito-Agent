from __future__ import annotations

import hashlib

import pytest

from cogito_agent.autonomy import (
    DecisionStore,
    FeedbackStore,
    NotificationGate,
    Outbox,
    ProactiveLoop,
    SchedulerEngine,
)
from cogito_agent.autonomy.events import AutonomyEvent
from cogito_agent.governance import AuditLogger, PolicyEngine, PolicyRule
from cogito_agent.shared import DecisionType
from cogito_agent.storage import Database


class _FailingOutbox(Outbox):
    def enqueue(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("outbox unavailable")


class _FailingAckSink:
    def acknowledge(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("api_key=sk-ack-secret-value")


def test_decision_and_outbox_roll_back_together() -> None:
    db = Database()
    db.initialize()
    db.migrate()
    policy = PolicyEngine(rules=[PolicyRule("*", "*", "*", DecisionType.allow)])
    loop = ProactiveLoop(
        SchedulerEngine(db),
        NotificationGate(db, policy_engine=policy),
        decision_store=DecisionStore(db),
        outbox=_FailingOutbox(db),
        feedback_store=FeedbackStore(db, AuditLogger(db)),
        policy_engine=policy,
        db=db,
    )
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        loop.process_event(AutonomyEvent(title="atomic", workspace_id="workspace"))
    decisions = db.connection.execute("SELECT COUNT(*) FROM notification_decisions").fetchone()[0]
    notifications = db.connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert decisions == 0
    assert notifications == 0
    db.close()


def test_ack_failure_is_persisted_and_redacted() -> None:
    db = Database()
    db.initialize()
    db.migrate()
    policy = PolicyEngine(rules=[PolicyRule("*", "*", "*", DecisionType.allow)])
    loop = ProactiveLoop(
        SchedulerEngine(db),
        NotificationGate(db, policy_engine=policy),
        feedback_store=FeedbackStore(db, AuditLogger(db)),
        policy_engine=policy,
        db=db,
        ack_sink=_FailingAckSink(),
    )
    loop.process_event(
        AutonomyEvent(
            title="ack",
            workspace_id="workspace",
            ack_token="source-token",
        )
    )
    row = db.connection.execute(
        "SELECT status, error_redacted FROM autonomy_acks WHERE ack_token_hash=?",
        (hashlib.sha256(b"source-token").hexdigest(),),
    ).fetchone()
    assert row is not None and row["status"] == "failed"
    assert "sk-ack-secret-value" not in str(row["error_redacted"])
    db.close()

"""Tests for governance paths in autonomy processing."""

from cogito_agent.autonomy import (
    DecisionAction,
    NotificationGate,
    Outbox,
    ProactiveLoop,
    SchedulerEngine,
)
from cogito_agent.autonomy.events import AutonomyEvent
from cogito_agent.governance import AuditLogger, PolicyEngine, PolicyRule
from cogito_agent.shared import DecisionType


def test_governance_allow_through_proactive_loop(
    db,
    wid: str,
    permissive_policy: PolicyEngine,
):
    gate = NotificationGate(db, policy_engine=permissive_policy)
    loop = ProactiveLoop(
        scheduler=SchedulerEngine(db),
        notification_gate=gate,
        db=db,
    )
    event = AutonomyEvent(title="gov allow", workspace_id=wid)
    decision = loop.process_event(event)
    assert decision.action == DecisionAction.push
    assert decision.reason_code == "allowed"


def test_governance_deny_through_proactive_loop(
    db,
    wid: str,
):
    deny_policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.deny),
        ]
    )
    gate = NotificationGate(db, policy_engine=deny_policy)
    loop = ProactiveLoop(
        scheduler=SchedulerEngine(db),
        notification_gate=gate,
        db=db,
    )
    event = AutonomyEvent(title="gov deny", workspace_id=wid)
    decision = loop.process_event(event)
    assert decision.action == DecisionAction.skip
    assert decision.reason_code == "governance_denied"


def test_governance_require_approval_through_proactive_loop(
    db,
    wid: str,
):
    approval_policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.require_approval),
        ]
    )
    gate = NotificationGate(db, policy_engine=approval_policy)
    loop = ProactiveLoop(
        scheduler=SchedulerEngine(db),
        notification_gate=gate,
        db=db,
    )
    event = AutonomyEvent(title="gov approval", workspace_id=wid)
    decision = loop.process_event(event)
    assert decision.action == DecisionAction.require_approval
    assert decision.requires_approval is True
    assert decision.reason_code == "requires_approval"


def test_governance_deny_writes_audit(
    db,
    wid: str,
):
    deny_policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.deny),
        ]
    )
    gate = NotificationGate(db, policy_engine=deny_policy)
    audit = AuditLogger(db)
    loop = ProactiveLoop(
        scheduler=SchedulerEngine(db),
        notification_gate=gate,
        audit_logger=audit,
        db=db,
    )
    event = AutonomyEvent(title="gov deny audit", workspace_id=wid)
    loop.process_event(event)
    cur = db.connection.execute(
        "SELECT action, decision, reason FROM audit_logs WHERE action = 'autonomy.decision_skip'"
    )
    rows = cur.fetchall()
    assert len(rows) >= 1
    assert rows[0]["decision"] == "deny"


def test_proactive_loop_requires_approval_no_outbox(
    db,
    wid: str,
):
    approval_policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.require_approval),
        ]
    )
    gate = NotificationGate(db, policy_engine=approval_policy)
    outbox = Outbox(db)
    loop = ProactiveLoop(
        scheduler=SchedulerEngine(db),
        notification_gate=gate,
        outbox=outbox,
        db=db,
    )
    event = AutonomyEvent(title="no push on approval", workspace_id=wid)
    loop.process_event(event)
    msgs = outbox.list_all(workspace_id=wid)
    assert len(msgs) == 0

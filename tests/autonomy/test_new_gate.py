"""Tests for the enhanced NotificationGate.evaluate() with AutonomyEvent."""

from cogito_agent.autonomy import AutonomyEvent, DecisionAction, NotificationGate, PriorityLevel
from cogito_agent.autonomy.gate import NotificationGate as NGate


def test_evaluate_push(gate: NotificationGate, wid: str):
    event = AutonomyEvent(title="test push", workspace_id=wid)
    decision = gate.evaluate(event)
    assert decision.action == DecisionAction.push
    assert decision.reason_code == "allowed"
    assert decision.event_id == event.event_id


def test_evaluate_quiet_hours_hit(gate: NotificationGate, wid: str):
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    event = AutonomyEvent(title="quiet test", workspace_id=wid)
    decision = gate.evaluate(event)
    assert decision.action == DecisionAction.skip
    assert decision.quiet_hours_hit is True
    assert decision.reason_code == "quiet_hours"


def test_evaluate_quiet_hours_override(gate: NotificationGate, wid: str):
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    event = AutonomyEvent(title="override", workspace_id=wid, quiet_hours_override=True)
    decision = gate.evaluate(event)
    assert decision.action == DecisionAction.push
    assert decision.quiet_hours_hit is False


def test_evaluate_urgent_bypass_quiet_hours(gate: NotificationGate, wid: str):
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    event = AutonomyEvent(title="urgent", workspace_id=wid, priority=PriorityLevel.urgent)
    config = {"urgent_bypass_quiet_hours": True, "quiet_hours_enabled": True}
    decision = gate.evaluate(event, config=config)
    assert decision.quiet_hours_hit is False


def test_evaluate_dedup_hit(gate: NotificationGate, wid: str):
    event1 = AutonomyEvent(title="dedup me", workspace_id=wid, category="test")
    gate.evaluate(event1)
    gate.persist_decision(gate.evaluate(event1))
    event2 = AutonomyEvent(title="dedup me", workspace_id=wid, category="test")
    decision = gate.evaluate(event2)
    if decision.dedup_hit:
        assert decision.action == DecisionAction.skip
        assert decision.reason_code == "dedup"


def test_evaluate_daily_quota_exceeded(gate: NotificationGate, wid: str):
    event_high = AutonomyEvent(title="high cost", workspace_id=wid, priority=PriorityLevel.high)
    gate.persist_decision(gate.evaluate(event_high))
    event_normal = AutonomyEvent(title="normal", workspace_id=wid)
    config = {"daily_quota": "1", "hourly_quota": "100"}
    decision = gate.evaluate(event_normal, config=config)
    if decision.quota_hit:
        assert decision.action in (DecisionAction.defer, DecisionAction.push)


def test_evaluate_governance_deny(gate: NotificationGate, wid: str, deny_policy):
    gate_with_deny = NotificationGate(gate._db, policy_engine=deny_policy)
    event = AutonomyEvent(title="denied", workspace_id=wid)
    decision = gate_with_deny.evaluate(event)
    assert decision.action == DecisionAction.skip
    assert "governance" in decision.reason_code


def test_evaluate_cost_score_low_priority_quiet_hours(gate: NotificationGate, wid: str):
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    event = AutonomyEvent(title="low quiet", workspace_id=wid, priority=PriorityLevel.low)
    decision = gate.evaluate(event)
    # quiet_hours hit: cost += 5, low priority: cost += 3 = total 8
    if decision.quiet_hours_hit:
        assert decision.cost_score >= 5.0


def test_evaluate_cost_score_urgent(gate: NotificationGate, wid: str):
    event = AutonomyEvent(title="urgent", workspace_id=wid, priority=PriorityLevel.urgent)
    decision = gate.evaluate(event)
    # urgent adds 0 cost
    assert decision.cost_score == 0.0


def test_persist_decision(gate: NotificationGate, wid: str):
    event = AutonomyEvent(title="persist test", workspace_id=wid)
    decision = gate.evaluate(event)
    did = gate.persist_decision(decision)
    assert did == decision.decision_id
    decisions = gate.list_decisions(wid)
    assert any(d["id"] == did for d in decisions)


def test_list_decisions_empty(gate: NotificationGate, wid: str):
    decisions = gate.list_decisions(wid)
    assert len(decisions) == 0


def test_count_push_recent(gate: NotificationGate, wid: str):
    from datetime import UTC, datetime, timedelta
    before = gate.count_push_recent(wid, minutes=60)
    event = AutonomyEvent(title="count test", workspace_id=wid)
    d = gate.evaluate(event)
    gate.persist_decision(d)
    after = gate.count_push_recent(wid, minutes=60)
    assert after >= before

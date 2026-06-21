"""Tests for DecisionStore."""

from cogito_agent.autonomy import DecisionStore


def test_save_and_list(decision_store: DecisionStore):
    decision_store.save_decision(
        decision_id="d1",
        event_id="e1",
        workspace_id="ws-1",
        user_id="u1",
        action="push",
        reason_code="allowed",
        reason="OK",
        cost_score=1.0,
        priority_score=2.0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    decisions = decision_store.list_decisions(workspace_id="ws-1")
    assert len(decisions) == 1
    assert decisions[0]["id"] == "d1"


def test_list_all_workspaces(decision_store: DecisionStore):
    decision_store.save_decision(
        decision_id="d1",
        event_id="e1",
        workspace_id="ws-1",
        user_id="",
        action="push",
        reason_code="ok",
        reason="",
        cost_score=0,
        priority_score=0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    decision_store.save_decision(
        decision_id="d2",
        event_id="e2",
        workspace_id="ws-2",
        user_id="",
        action="skip",
        reason_code="quiet_hours",
        reason="",
        cost_score=0,
        priority_score=0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    decisions = decision_store.list_decisions()
    assert len(decisions) >= 2


def test_get_decision(decision_store: DecisionStore):
    decision_store.save_decision(
        decision_id="d-get",
        event_id="e-get",
        workspace_id="ws-1",
        user_id="",
        action="push",
        reason_code="ok",
        reason="test",
        cost_score=2.5,
        priority_score=3.0,
        dedup_hit=True,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    d = decision_store.get_decision("d-get")
    assert d is not None
    assert d["event_id"] == "e-get"
    assert d["cost_score"] == 2.5
    assert d["dedup_hit"] == 1


def test_get_decision_not_found(decision_store: DecisionStore):
    d = decision_store.get_decision("nonexistent")
    assert d is None


def test_count_push_recent(decision_store: DecisionStore):
    before = decision_store.count_push_recent("ws-1", minutes=60)
    decision_store.save_decision(
        decision_id="d-count",
        event_id="e-count",
        workspace_id="ws-1",
        user_id="",
        action="push",
        reason_code="ok",
        reason="",
        cost_score=0,
        priority_score=0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    after = decision_store.count_push_recent("ws-1", minutes=60)
    assert after == before + 1


def test_save_requires_approval(decision_store: DecisionStore):
    decision_store.save_decision(
        decision_id="d-approve",
        event_id="e-approve",
        workspace_id="ws-1",
        user_id="",
        action="require_approval",
        reason_code="needs_ok",
        reason="",
        cost_score=0,
        priority_score=0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=True,
    )
    d = decision_store.get_decision("d-approve")
    assert d["requires_approval"] == 1

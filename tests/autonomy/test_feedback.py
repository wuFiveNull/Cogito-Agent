"""Tests for FeedbackStore."""

from cogito_agent.autonomy import FeedbackStore


def test_record_feedback(feedback_store: FeedbackStore):
    fid = feedback_store.record_feedback(
        decision_id="d-fb-1",
        event_id="e-fb-1",
        value="useful",
        workspace_id="ws-1",
    )
    assert fid is not None


def test_get_feedback_for_decision(feedback_store: FeedbackStore):
    feedback_store.record_feedback(
        decision_id="d-fb-2",
        event_id="e-fb-2",
        value="not_useful",
        workspace_id="ws-1",
    )
    entries = feedback_store.get_feedback_for_decision("d-fb-2")
    assert len(entries) == 1
    assert entries[0]["value"] == "not_useful"


def test_get_recent_feedback(feedback_store: FeedbackStore):
    feedback_store.record_feedback(
        decision_id="d1",
        event_id="e1",
        value="too_many",
        workspace_id="ws-1",
    )
    feedback_store.record_feedback(
        decision_id="d2",
        event_id="e2",
        value="wrong_time",
        workspace_id="ws-1",
    )
    recent = feedback_store.get_recent_feedback("ws-1", limit=5)
    assert len(recent) >= 2
    assert "too_many" in recent
    assert "wrong_time" in recent


def test_feedback_values_enum():
    from cogito_agent.autonomy import FeedbackValue

    assert FeedbackValue.useful.value == "useful"
    assert FeedbackValue.not_useful.value == "not_useful"
    assert FeedbackValue.too_many.value == "too_many"
    assert FeedbackValue.wrong_time.value == "wrong_time"
    assert FeedbackValue.irrelevant.value == "irrelevant"


def test_record_feedback_with_comment(feedback_store: FeedbackStore):
    feedback_store.record_feedback(
        decision_id="d-fb-c",
        event_id="e-fb-c",
        value="useful",
        comment="great suggestion",
        workspace_id="ws-1",
    )
    entries = feedback_store.get_feedback_for_decision("d-fb-c")
    assert len(entries) == 1
    assert entries[0]["comment"] == "great suggestion"


def test_feedback_empty_for_unknown_decision(feedback_store: FeedbackStore):
    entries = feedback_store.get_feedback_for_decision("nonexistent")
    assert len(entries) == 0

"""Tests for Outbox."""

from cogito_agent.autonomy import Outbox


def test_enqueue(outbox: Outbox):
    mid = outbox.enqueue(
        event_id="e1",
        decision_id="d1",
        title="test msg",
        body="hello",
        workspace_id="ws-1",
    )
    assert mid is not None
    assert len(mid) > 0


def test_list_pending(outbox: Outbox):
    outbox.enqueue(event_id="e1", decision_id="d1", title="pending1", workspace_id="ws-1")
    outbox.enqueue(event_id="e2", decision_id="d2", title="pending2", workspace_id="ws-1")
    pending = outbox.list_pending(workspace_id="ws-1")
    assert len(pending) == 2


def test_mark_sent(outbox: Outbox):
    mid = outbox.enqueue(event_id="e1", decision_id="d1", title="mark sent", workspace_id="ws-1")
    outbox.mark_sent(mid)
    msg = outbox.get_message(mid)
    assert msg["status"] == "sent"
    assert msg["sent_at"] is not None


def test_mark_failed(outbox: Outbox):
    mid = outbox.enqueue(event_id="e1", decision_id="d1", title="mark failed", workspace_id="ws-1")
    outbox.mark_failed(mid, error="connection error")
    msg = outbox.get_message(mid)
    assert msg["status"] == "failed"


def test_list_all(outbox: Outbox):
    outbox.enqueue(event_id="e1", decision_id="d1", title="all1", workspace_id="ws-1")
    outbox.enqueue(event_id="e2", decision_id="d2", title="all2", workspace_id="ws-1")
    all_msgs = outbox.list_all(workspace_id="ws-1")
    assert len(all_msgs) == 2


def test_get_message_not_found(outbox: Outbox):
    msg = outbox.get_message("nonexistent")
    assert msg is None


def test_empty_list(outbox: Outbox):
    pending = outbox.list_pending(workspace_id="nonexistent")
    assert len(pending) == 0

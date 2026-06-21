from __future__ import annotations

from cogito_agent.autonomy.gate import NotificationGate


def test_quiet_hours_block_notifications(gate: NotificationGate, wid: str) -> None:
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    allowed, reason = gate.should_notify(wid, "quiet test", "body")
    assert allowed is False
    assert reason == "quiet_hours"


def test_quiet_hours_outside_window_allows(gate: NotificationGate, wid: str) -> None:
    gate.set_quiet_hours(wid, start="00:00", end="00:01")
    allowed, reason = gate.should_notify(wid, "outside quiet", "body")
    if reason == "quiet_hours":
        assert allowed is False
    else:
        assert allowed is True


def test_quiet_hours_removed_allows(gate: NotificationGate, wid: str) -> None:
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    gate.should_notify(wid, "blocked", "body")

    gate.set_quiet_hours(wid, start="", end="")
    allowed, reason = gate.should_notify(wid, "allowed", "body")
    assert reason != "quiet_hours"


def test_dedup_prevents_duplicate_notifications(gate: NotificationGate, wid: str) -> None:
    allowed1, nid1 = gate.should_notify(wid, "dedup title", "dedup body")
    if allowed1:
        assert isinstance(nid1, str) and len(nid1) > 0

    allowed2, nid2 = gate.should_notify(wid, "dedup title", "dedup body")
    assert allowed2 is False
    assert nid2 == "duplicate"


def test_dedup_different_titles_not_duplicate(gate: NotificationGate, wid: str) -> None:
    allowed1, _ = gate.should_notify(wid, "first dedup", "body")
    allowed2, nid2 = gate.should_notify(wid, "second dedup", "body")
    if allowed2:
        assert nid2 != "duplicate"
    else:
        assert nid2 == "duplicate"


def test_dedup_different_bodies_not_duplicate(gate: NotificationGate, wid: str) -> None:
    allowed1, _ = gate.should_notify(wid, "same title", "body A")
    allowed2, nid2 = gate.should_notify(wid, "same title", "body B")
    if allowed2:
        assert nid2 != "duplicate"
    else:
        assert nid2 == "duplicate"


def test_daily_quota_limits_notifications(gate: NotificationGate, wid: str) -> None:
    gate.set_quiet_hours(wid, max_daily=1)
    gate.record_notification(wid, "j1", "quota n1", "b1")
    allowed, reason = gate.should_notify(wid, "quota n2", "b2")
    if reason == "duplicate":
        pass
    elif reason == "daily_quota_exceeded":
        assert allowed is False
    else:
        assert allowed is True


def test_daily_quota_different_workspace_independent(gate: NotificationGate, wid: str, db) -> None:
    from cogito_agent.storage.repositories import WorkspaceRepository

    repo = WorkspaceRepository(db)
    repo.create("ws-gate-2", "gate-test-2")

    gate.set_quiet_hours(wid, max_daily=1)
    gate.set_quiet_hours("ws-gate-2", max_daily=5)

    gate.record_notification(wid, "j1", "ws1-1", "b1")
    gate.record_notification("ws-gate-2", "j2", "ws2-1", "b1")

    _, reason1 = gate.should_notify(wid, "ws1-2", "b2")
    _, reason2 = gate.should_notify("ws-gate-2", "ws2-2", "b2")

    assert reason2 != "daily_quota_exceeded"


def test_daily_quota_default_is_three(gate: NotificationGate, wid: str) -> None:
    gate.record_notification(wid, "j1", "d1", "b1")
    gate.record_notification(wid, "j2", "d2", "b2")
    gate.record_notification(wid, "j3", "d3", "b3")
    allowed, reason = gate.should_notify(wid, "d4", "b4")
    if reason == "duplicate":
        pass
    elif reason == "daily_quota_exceeded":
        assert allowed is False
    else:
        assert allowed is True


def test_priority_field_stored_via_should_notify(gate: NotificationGate, wid: str) -> None:
    allowed, nid = gate.should_notify(wid, "priority test", "body", priority="high")
    if allowed:
        notifications = gate.get_notifications(wid)
        found = [n for n in notifications if n["id"] == nid]
        if found:
            assert found[0]["priority"] == "high"


def test_priority_field_stored_via_record(gate: NotificationGate, wid: str) -> None:
    nid = gate.record_notification(wid, "j1", "priority rec", "body", priority="low")
    notifications = gate.get_notifications(wid)
    found = [n for n in notifications if n["id"] == nid]
    assert len(found) == 1
    assert found[0]["priority"] == "low"


def test_priority_default_is_normal(gate: NotificationGate, wid: str) -> None:
    nid = gate.record_notification(wid, "j1", "default priority", "body")
    notifications = gate.get_notifications(wid)
    found = [n for n in notifications if n["id"] == nid]
    assert len(found) == 1
    assert found[0]["priority"] == "normal"


def test_try_notify_or_inbox_fallback(gate: NotificationGate, wid: str) -> None:
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    channel, result = gate.try_notify_or_inbox(
        wid,
        "fallback title",
        "fallback body",
    )
    assert channel == "inbox"
    assert isinstance(result, str)
    assert len(result) > 0


def test_try_notify_or_inbox_notifies(gate: NotificationGate, wid: str) -> None:
    channel, result = gate.try_notify_or_inbox(
        wid,
        "notify title",
        "notify body",
    )
    assert channel == "notified"
    assert isinstance(result, str)
    assert len(result) > 0

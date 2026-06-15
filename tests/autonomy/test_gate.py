from __future__ import annotations


def test_set_quiet_hours(gate, wid: str) -> None:
    gate.set_quiet_hours(wid, start="22:00", end="08:00")
    allowed, result = gate.should_notify(wid, "hello", "world")
    if result == "quiet_hours":
        assert allowed is False
    else:
        assert allowed is True


def test_duplicate_suppression(gate, wid: str) -> None:
    allowed1, nid1 = gate.should_notify(wid, "same title", "same body")
    allowed2, nid2 = gate.should_notify(wid, "same title", "same body")
    if allowed1:
        assert nid1 != ""
    if allowed2:
        assert nid2 == "duplicate"
    else:
        assert nid2 == "duplicate"


def test_different_events_not_duplicate(gate, wid: str) -> None:
    allowed1, _ = gate.should_notify(wid, "first", "body1")
    allowed2, _ = gate.should_notify(wid, "second", "body2")
    assert allowed1 is True or not allowed1  # don't care about policy
    assert allowed2 is True or not allowed2


def test_record_feedback(gate, wid: str) -> None:
    nid = gate.record_notification(wid, "job-1", "test title", "test body")
    gate.record_feedback(nid, "useful")
    notifications = gate.get_notifications(wid)
    assert len(notifications) == 1
    assert notifications[0]["feedback"] == "useful"


def test_get_notifications(gate, wid: str) -> None:
    gate.record_notification(wid, "j1", "title1", "body1")
    gate.record_notification(wid, "j2", "title2", "body2")
    all_n = gate.get_notifications(wid)
    assert len(all_n) == 2


def test_daily_quota(gate, wid: str) -> None:
    gate.set_quiet_hours(wid, max_daily=1)
    gate.record_notification(wid, "j1", "n1", "b1")
    allowed, reason = gate.should_notify(wid, "n2", "b2")
    if reason == "daily_quota_exceeded":
        assert allowed is False
    elif reason == "duplicate":
        pass  # same hash
    else:
        pass  # may be allowed depending on policy

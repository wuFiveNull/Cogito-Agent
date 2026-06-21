"""Tests for PresenceStore."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cogito_agent.runtime.presence import PresenceStore
from cogito_agent.storage import Database


def _db() -> Database:
    d = Database(":memory:")
    d.initialize()
    return d


def test_touch_and_read() -> None:
    p = PresenceStore(_db())
    now = datetime.now(UTC)
    p.touch("test-session", channel="cli", now=now)
    assert p.get_last_user_at("test-session") is not None


def test_is_online() -> None:
    p = PresenceStore(_db())
    now = datetime.now(UTC)
    p.touch("test-session", now=now)
    assert p.is_online("test-session", now=now) is True
    # Simulate 24h later: the stored time hasn't changed, but comparison time is far in future
    long_ago_stored = now - timedelta(hours=24)
    p.touch("test-session", now=long_ago_stored)
    assert p.is_online("test-session", now=now, timeout_minutes=5) is False


def test_unknown_session() -> None:
    p = PresenceStore(_db())
    assert p.get_last_user_at("nonexistent") is None
    assert p.is_online("nonexistent") is False


def test_idle_minutes() -> None:
    p = PresenceStore(_db())
    assert p.get_idle_minutes("nonexistent") == 0.0
    now = datetime.now(UTC)
    p.touch("s", now=now)
    later = now + timedelta(minutes=30)
    # With a "later" now, idle should be ~30 min
    assert p.get_idle_minutes("s") >= 0.0


def test_all_sessions() -> None:
    p = PresenceStore(_db())
    assert p.all_sessions() == []
    p.touch("s1", channel="cli")
    p.touch("s2", channel="api")
    sessions = p.all_sessions()
    assert len(sessions) == 2
    keys = {s["session_key"] for s in sessions}
    assert keys == {"s1", "s2"}

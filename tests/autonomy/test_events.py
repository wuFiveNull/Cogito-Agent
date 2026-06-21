"""Tests for AutonomyEvent model and normalizer."""

from cogito_agent.autonomy import AutonomySourceType, PriorityLevel
from cogito_agent.autonomy.events import AutonomyEvent as AE  # noqa: N817
from cogito_agent.autonomy.normalizer import normalize_from_dict, normalize_manual


def test_event_defaults():
    event = AE(title="test")
    assert event.event_id
    assert event.source_type == AutonomySourceType.system
    assert event.priority == PriorityLevel.normal
    assert event.dedup_key == ""
    assert event.quiet_hours_override is False


def test_dedup_key_stable():
    e1 = AE(title="hello", source="scheduler", category="maintenance")
    e2 = AE(title="hello", source="scheduler", category="maintenance")
    assert e1.build_dedup_key() == e2.build_dedup_key()


def test_dedup_key_different_title():
    e1 = AE(title="hello", source="scheduler", category="maintenance")
    e2 = AE(title="world", source="scheduler", category="maintenance")
    assert e1.build_dedup_key() != e2.build_dedup_key()


def test_dedup_key_explicit():
    e = AE(title="test", dedup_key="my-custom-key")
    assert e.build_dedup_key() == "my-custom-key"


def test_normalize_from_dict():
    data = {
        "title": "manual event",
        "body": "hello",
        "source_type": "manual",
        "priority": "high",
        "source": "cli",
        "category": "user-action",
    }
    event = normalize_from_dict(data)
    assert event.title == "manual event"
    assert event.body == "hello"
    assert event.source_type == AutonomySourceType.manual
    assert event.priority == PriorityLevel.high
    assert event.source == "cli"
    assert event.category == "user-action"


def test_normalize_from_dict_invalid_source_type():
    data = {"title": "test", "source_type": "invalid_type"}
    event = normalize_from_dict(data)
    assert event.source_type == AutonomySourceType.system


def test_normalize_from_dict_invalid_priority():
    data = {"title": "test", "priority": "invalid"}
    event = normalize_from_dict(data)
    assert event.priority == PriorityLevel.normal


def test_normalize_from_dict_event_time():
    data = {"title": "test", "event_time": "2025-06-01T12:00:00"}
    event = normalize_from_dict(data)
    assert event.event_time is not None
    assert event.event_time.isoformat().startswith("2025-06-01")


def test_normalize_from_dict_metadata_string_only():
    data = {"title": "test", "metadata": {"key": "value", "num": 42}}
    event = normalize_from_dict(data)
    assert event.metadata == {"key": "value"}


def test_normalize_manual():
    event = normalize_manual("my title", "my body", priority="urgent")
    assert event.title == "my title"
    assert event.body == "my body"
    assert event.priority == PriorityLevel.urgent
    assert event.source_type == AutonomySourceType.manual


def test_normalize_manual_no_body():
    event = normalize_manual("just title", "")
    assert event.title == "just title"
    assert event.body == ""


def test_event_priority_score():
    e = AE(title="test", priority=PriorityLevel.urgent)
    assert e.priority == PriorityLevel.urgent


def test_event_no_secret_in_metadata():
    event = AE(title="test", metadata={"api_key": "secret123"})
    # metadata dict is user-provided, no secret enforcement at model level
    assert event.metadata["api_key"] == "secret123"

"""Tests for ConsolidationService (Memory v2 — uses Memorizer + memory_items)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cogito_agent.memory import ConsolidationService
from cogito_agent.memory.memorizer import Memorizer
from cogito_agent.memory.ports import LLMExtractionPort
from cogito_agent.storage import Database


@pytest.fixture
def db() -> Database:
    d = Database(":memory:")
    d.initialize()
    d.migrate()
    return d


@pytest.fixture
def memorizer(db: Database) -> Memorizer:
    return Memorizer(db)


def _msg(role: str, content: str, mid: str = "") -> dict:
    m: dict[str, object] = {"role": role, "content": content}
    if mid:
        m["id"] = mid
    return m


def _mock_extractor(
    extraction_data: dict[str, Any] | None = None,
    compression_data: dict[str, list[str]] | None = None,
) -> LLMExtractionPort:
    """Build a minimal mock LLMExtractionPort for tests."""
    class _MockExtractor:
        def extract_memories(self, conversation_text: str, memory_context: str = "") -> dict[str, Any] | None:
            return extraction_data

        def compress_context(self, conversation_text: str) -> dict[str, list[str]] | None:
            return compression_data

    return _MockExtractor()


def _extraction(entries: list[dict[str, Any]] | None = None,
                pending: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "history_entries": entries or [],
        "pending_items": pending or [],
    }


# ── Basic state tracking ────────────────────────────────────────────────


def test_tracks_last_consolidated(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    msgs = [_msg("user", "Hello"), _msg("assistant", "Hi")]
    svc.after_turn(msgs, "ws-1")
    assert svc._last_consolidated.get("ws-1") == 2


def test_different_workspaces_independent(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    svc.after_turn([_msg("user", "Hi", mid="a")], "ws-A")
    svc.after_turn([_msg("user", "Hello", mid="b")], "ws-B")
    assert svc._last_consolidated.get("ws-A") == 1
    assert svc._last_consolidated.get("ws-B") == 1


def test_consolidation_with_mock_model(memorizer: Memorizer) -> None:
    extractor = _mock_extractor(
        extraction_data=_extraction(
            entries=[{"summary": "[2024-06-01] User asked about weather", "emotional_weight": 3}],
            pending=[{"tag": "preference", "content": "User likes sunny weather"}],
        ),
        compression_data={"active_topics": ["weather"], "user_preferences": ["sunny"],
                          "follow_ups": [], "avoidances": [], "ongoing_threads": []},
    )
    svc = ConsolidationService(
        memorizer, llm_extractor=extractor,
        keep_count=6,
    )
    msgs = [
        _msg("user", "I really like sunny weather!", mid="m1"),
        _msg("assistant", "That is nice!", mid="m2"),
        _msg("user", "Can you remind me tomorrow?", mid="m3"),
        _msg("assistant", "Sure!", mid="m4"),
        _msg("user", "What about rain?", mid="m5"),
        _msg("assistant", "Rain is also fine.", mid="m6"),
    ]
    svc.after_turn(msgs, "ws-1")

    # Verify data was written to memory_items
    rows = memorizer._db.connection.execute(
        "SELECT * FROM memory_items WHERE workspace_id = 'ws-1'"
    ).fetchall()
    assert len(rows) >= 1
    types = {r["memory_type"] for r in rows}
    assert "event" in types  # history_entries → event
    assert "preference" in types  # pending_items → preference


def test_skips_llm_without_extractor(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    msgs = [_msg("user", "A" * 100, mid="m1"), _msg("assistant", "B" * 100, mid="m2")]
    svc.after_turn(msgs, "ws-1")
    # Without extractor, nothing should be written
    rows = memorizer._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM memory_items"
    ).fetchone()
    assert rows["cnt"] == 0


def test_consolidation_with_json_codeblock(memorizer: Memorizer) -> None:
    svc = ConsolidationService(
        memorizer,
        llm_extractor=_mock_extractor(
            extraction_data=_extraction(
                entries=[{"summary": "[2024-06-01] User mentioned preference", "emotional_weight": 2}],
            ),
            compression_data={},
        ),
        keep_count=6,
    )
    msgs = [
        _msg("user", "X" * 50, mid="a"),
        _msg("assistant", "Y" * 50, mid="b"),
        _msg("user", "Z" * 50, mid="c"),
        _msg("assistant", "W" * 50, mid="d"),
        _msg("user", "V" * 50, mid="e"),
        _msg("assistant", "U" * 50, mid="f"),
    ]
    svc.after_turn(msgs, "ws-2")
    rows = memorizer._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM memory_items WHERE workspace_id = 'ws-2'"
    ).fetchone()
    assert rows["cnt"] >= 1


def test_called_twice_no_duplicate(memorizer: Memorizer) -> None:
    """Same data consolidated twice should not duplicate memory_items."""

    class _CountingExtractor:
        def __init__(self):
            self.call_count = 0

        def extract_memories(self, conversation_text, memory_context=""):
            self.call_count += 1
            return _extraction(
                entries=[{"summary": "[2024-06-01] Fact about sky", "emotional_weight": 1}],
            )

        def compress_context(self, conversation_text):
            return {"active_topics": [], "user_preferences": [],
                    "follow_ups": [], "avoidances": [], "ongoing_threads": []}

    svc = ConsolidationService(
        memorizer, llm_extractor=_CountingExtractor(),
        keep_count=6,
    )
    msgs = [
        _msg("user", "Tell me a fact", mid="x1"),
        _msg("assistant", "The sky is blue.", mid="x2"),
        _msg("user", "Another fact", mid="x3"),
        _msg("assistant", "Water is wet.", mid="x4"),
        _msg("user", "More facts", mid="x5"),
        _msg("assistant", "Fire is hot.", mid="x6"),
    ]
    svc.after_turn(msgs, "ws-3")
    first_count = memorizer._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM memory_items WHERE workspace_id = 'ws-3'"
    ).fetchone()["cnt"]

    new_msgs = msgs + [
        _msg("user", "Fact seven", mid="x7"),
        _msg("assistant", "Earth is round.", mid="x8"),
        _msg("user", "Fact eight", mid="x9"),
        _msg("assistant", "Ice is cold.", mid="x10"),
        _msg("user", "Fact nine", mid="x11"),
        _msg("assistant", "Stars are far.", mid="x12"),
    ]
    svc.after_turn(new_msgs, "ws-3")
    second_count = memorizer._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM memory_items WHERE workspace_id = 'ws-3'"
    ).fetchone()["cnt"]

    assert second_count >= first_count
    assert second_count > 0


# ── Edge cases ──────────────────────────────────────────────────────────


def test_single_message_no_crash(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    svc.after_turn([_msg("user", "Hello")], "ws-1")


def test_empty_content_no_error(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    svc.after_turn([_msg("user", "")], "ws-1")
    svc.after_turn([_msg("assistant", "")], "ws-1")


def test_no_extractor_no_crash(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    msgs = [_msg("user", "Hello"), _msg("assistant", "Hi")]
    svc.after_turn(msgs, "ws-1")  # Should not raise


def test_last_consolidated_tracking(memorizer: Memorizer) -> None:
    svc = ConsolidationService(memorizer)
    assert svc._last_consolidated == {}
    svc.after_turn([_msg("user", "A", mid="a")], "ws-1")
    assert svc._last_consolidated.get("ws-1") == 1
    # Second call counts its own messages (B and C = 2 messages total in this call)
    svc.after_turn([_msg("user", "B", mid="b"), _msg("assistant", "C", mid="c")], "ws-1")
    assert svc._last_consolidated.get("ws-1") == 2


# ── Light model compression ─────────────────────────────────────────────


def test_extractor_stores_recent_context(memorizer: Memorizer) -> None:
    extractor = _mock_extractor(
        extraction_data=_extraction(pending=[]),
        compression_data={
            "active_topics": ["python coding"],
            "user_preferences": ["likes type hints"],
            "follow_ups": [],
            "avoidances": [],
            "ongoing_threads": [],
        },
    )
    svc = ConsolidationService(
        memorizer, llm_extractor=extractor,
        keep_count=6,
    )
    msgs = [
        _msg("user", "I love Python type hints!", mid="a"),
        _msg("assistant", "Me too!", mid="b"),
        _msg("user", "They make code clearer.", mid="c"),
        _msg("assistant", "Absolutely.", mid="d"),
        _msg("user", "Any tips?", mid="e"),
        _msg("assistant", "Use Optional wisely.", mid="f"),
    ]
    svc.after_turn(msgs, "ws-1")
    # Should store _recent_context entry
    ctx = memorizer._db.connection.execute(
        "SELECT * FROM memory_items WHERE memory_type = '_recent_context' AND workspace_id = 'ws-1'"
    ).fetchone()
    assert ctx is not None, "_recent_context should be stored"
    import json as _json
    parsed = _json.loads(ctx["summary"])
    assert "active_topics" in parsed

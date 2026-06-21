"""Tests for Memorizer — the structured memory writer."""

from __future__ import annotations

from cogito_agent.memory.memorizer import Memorizer, _content_id
from cogito_agent.storage import Database


def _db() -> Database:
    d = Database(":memory:")
    d.initialize()
    d.migrate()
    return d


def test_content_id_deterministic() -> None:
    """Same text + type → same hash."""
    assert _content_id("hello", "profile") == _content_id("hello", "profile")


def test_content_id_different_type() -> None:
    """Different types → different hashes for same text."""
    assert _content_id("hello", "profile") != _content_id("hello", "preference")


def test_save_creates_new() -> None:
    db = _db()
    m = Memorizer(db)
    result = m.save("User likes Python", "preference", workspace_id="ws1")
    assert result["action"] == "created"
    assert result["id"]

    row = db.connection.execute(
        "SELECT * FROM memory_items WHERE id = ?", (result["id"],)
    ).fetchone()
    assert row is not None
    assert row["memory_type"] == "preference"
    assert row["reinforcement"] == 1


def test_save_reinforces_existing() -> None:
    db = _db()
    m = Memorizer(db)
    r1 = m.save("User likes Python", "preference", workspace_id="ws1")
    r2 = m.save("User likes Python", "preference", workspace_id="ws1")
    assert r1["id"] == r2["id"]
    assert r2["action"] == "reinforced"

    row = db.connection.execute(
        "SELECT reinforcement FROM memory_items WHERE id = ?", (r1["id"],)
    ).fetchone()
    assert row["reinforcement"] == 2


def test_save_empty_summary() -> None:
    db = _db()
    m = Memorizer(db)
    result = m.save("", "general", workspace_id="ws1")
    assert result["action"] == "skipped"


def test_save_different_types_no_dedup() -> None:
    """Same text, different types → separate entries."""
    db = _db()
    m = Memorizer(db)
    r1 = m.save("User likes Python", "preference", workspace_id="ws1")
    r2 = m.save("User likes Python", "profile", workspace_id="ws1")
    assert r1["id"] != r2["id"]


def test_save_multiple_workspaces() -> None:
    """Different workspaces → separate entries."""
    db = _db()
    m = Memorizer(db)
    r1 = m.save("User likes Python", "preference", workspace_id="ws1")
    r2 = m.save("User likes Python", "preference", workspace_id="ws2")
    assert r1["id"] != r2["id"]


class _MockEmbedder:
    def embed_text(self, text: str) -> list[float]:
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        vec = [(b - 128) / 128.0 for b in h[:16]]
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec] if norm > 0 else vec


def test_save_with_supersede_falls_back_without_embedder() -> None:
    """Without embedder, save_with_supersede acts like save."""
    db = _db()
    m = Memorizer(db)
    r = m.save_with_supersede("hello", "general", workspace_id="ws1")
    assert r["action"] in ("created",)


def test_save_with_supersede_reinforces_exact_match() -> None:
    db = _db()
    m = Memorizer(db, embedder=_MockEmbedder())
    r1 = m.save_with_supersede("Exact same text", "preference", workspace_id="ws1")
    r2 = m.save_with_supersede("Exact same text", "preference", workspace_id="ws1")
    assert r1["id"] == r2["id"]
    assert r2["action"] == "reinforced"


def test_extra_json_stored() -> None:
    db = _db()
    m = Memorizer(db)
    m.save("test", "general", workspace_id="ws1", extra={"source": "chat", "tags": ["a"]})
    row = db.connection.execute(
        "SELECT extra_json FROM memory_items WHERE memory_type = 'general' LIMIT 1"
    ).fetchone()
    assert row is not None
    import json
    parsed = json.loads(row["extra_json"])
    assert parsed["source"] == "chat"

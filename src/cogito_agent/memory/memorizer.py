"""Memorizer — structured memory writer with dedup, merge, and supersede.

Replaces the old file-based MarkdownMemoryStore (MEMORY.md / HISTORY.md /
PENDING.md) with structured SQLite entries in the ``memory_items`` table.

Design follows Akashic's memory2/memorizer.py pattern:
1. content_hash dedup → reinforcement++
2. Semantic similarity merge (≥ threshold)
3. High-similarity supersede (old entries marked superseded)
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.retrieval import EmbeddingPort

logger = logging.getLogger(__name__)


def _content_id(text: str, memory_type: str = "") -> str:
    """SHA256-based content hash for dedup."""
    raw = f"{memory_type}:{text.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class Memorizer:
    """Write structured memories to the ``memory_items`` table.

    Each memory is a standalone row with type, summary, content_hash,
    reinforcement count, and optional emotional_weight + extra metadata.
    """

    def __init__(self, db: Any, embedder: EmbeddingPort | None = None) -> None:
        self._db = db
        self._embedder = embedder

    # ── public API ─────────────────────────────────────────────────────────

    def save(
        self,
        summary: str,
        memory_type: str,
        *,
        workspace_id: str = "default",
        source_ref: str = "",
        happened_at: str | None = None,
        emotional_weight: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        """Write a memory: dedup by content_hash → reinforce or insert.

        Returns ``{"id": str, "action": "created"|"reinforced"}``.
        """
        summary = summary.strip()
        if not summary:
            return {"id": "", "action": "skipped"}
        cid = _content_id(summary, memory_type)
        emotional_weight = max(0, min(10, int(emotional_weight)))

        existing = self._db.connection.execute(
            "SELECT id, reinforcement FROM memory_items"
            " WHERE workspace_id = ? AND content_hash = ? AND memory_type = ?"
            " AND status = 'active'",
            (workspace_id, cid, memory_type),
        ).fetchone()

        if existing:
            self._db.connection.execute(
                "UPDATE memory_items SET reinforcement = reinforcement + 1,"
                " emotional_weight = MAX(emotional_weight, ?),"
                " updated_at = ?"
                " WHERE id = ?",
                (emotional_weight, datetime.now(UTC).isoformat(), str(existing["id"])),
            )
            self._db.connection.commit()
            return {"id": str(existing["id"]), "action": "reinforced"}

        mid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO memory_items"
            " (id, workspace_id, memory_type, summary, content_hash,"
            "  reinforcement, emotional_weight, extra_json, source_ref,"
            "  happened_at, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 'active', ?, ?)",
            (
                mid,
                workspace_id,
                memory_type,
                summary,
                cid,
                emotional_weight,
                json.dumps(extra or {}, ensure_ascii=False),
                source_ref,
                happened_at,
                now,
                now,
            ),
        )
        self._db.connection.commit()
        return {"id": mid, "action": "created"}

    def save_with_supersede(
        self,
        summary: str,
        memory_type: str,
        *,
        workspace_id: str = "default",
        source_ref: str = "",
        happened_at: str | None = None,
        emotional_weight: int = 0,
        extra: dict[str, Any] | None = None,
        merge_threshold: float = 0.70,
        supersede_threshold: float = 0.90,
    ) -> dict[str, object]:
        """Write with semantic merge and supersede.

        Requires an embedder. When a semantically similar (≥ *merge_threshold*)
        active memory exists, merge the new info into the existing one instead
        of creating a new entry. When similarity ≥ *supersede_threshold*, mark
        the old entry as ``superseded`` and create a fresh one.
        """
        summary = summary.strip()
        if not summary:
            return {"id": "", "action": "skipped"}

        # Without embedder, fall back to simple save
        if not self._embedder:
            return self.save(
                summary, memory_type,
                workspace_id=workspace_id,
                source_ref=source_ref,
                happened_at=happened_at,
                emotional_weight=emotional_weight,
                extra=extra,
            )

        cid = _content_id(summary, memory_type)
        emotional_weight = max(0, min(10, int(emotional_weight)))
        now = datetime.now(UTC).isoformat()

        # Existing by exact hash
        existing = self._db.connection.execute(
            "SELECT id, summary, reinforcement FROM memory_items"
            " WHERE workspace_id = ? AND content_hash = ? AND memory_type = ?"
            " AND status = 'active'",
            (workspace_id, cid, memory_type),
        ).fetchone()

        if existing:
            self._db.connection.execute(
                "UPDATE memory_items SET reinforcement = reinforcement + 1,"
                " emotional_weight = MAX(emotional_weight, ?),"
                " updated_at = ? WHERE id = ?",
                (emotional_weight, now, str(existing["id"])),
            )
            self._db.connection.commit()
            return {"id": str(existing["id"]), "action": "reinforced"}

        # Semantic supersede: find similar active entries
        try:
            vec = self._embedder.embed_text(summary)
            rows = self._db.connection.execute(
                "SELECT id, summary, content_hash, reinforcement FROM memory_items"
                " WHERE workspace_id = ? AND memory_type = ? AND status = 'active'"
                " ORDER BY updated_at DESC LIMIT 20",
                (workspace_id, memory_type),
            ).fetchall()
            for row in rows:
                sim = self._compute_similarity(summary, str(row["summary"]))
                if sim is None:
                    continue
                if sim >= supersede_threshold:
                    # Supersede: mark old as superseded, create new
                    self._db.connection.execute(
                        "UPDATE memory_items SET status = 'superseded', updated_at = ?"
                        " WHERE id = ?",
                        (now, str(row["id"])),
                    )
                    break
                if sim >= merge_threshold:
                    # Merge: append new info to existing summary
                    merged = str(row["summary"]).rstrip(".") + "; " + summary
                    self._db.connection.execute(
                        "UPDATE memory_items SET summary = ?, reinforcement = reinforcement + 1,"
                        " updated_at = ? WHERE id = ?",
                        (merged, now, str(row["id"])),
                    )
                    self._db.connection.commit()
                    return {"id": str(row["id"]), "action": "merged"}
        except Exception:
            logger.exception("Semantic merge/supersede failed, falling back to insert")

        # Fresh insert
        mid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_items"
            " (id, workspace_id, memory_type, summary, content_hash,"
            "  reinforcement, emotional_weight, extra_json, source_ref,"
            "  happened_at, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 'active', ?, ?)",
            (
                mid,
                workspace_id,
                memory_type,
                summary,
                cid,
                emotional_weight,
                json.dumps(extra or {}, ensure_ascii=False),
                source_ref,
                happened_at,
                now,
                now,
            ),
        )
        self._db.connection.commit()
        return {"id": mid, "action": "created"}

    # ── helpers ───────────────────────────────────────────────────────────

    def _compute_similarity(self, a: str, b: str) -> float | None:
        """Compute cosine similarity between two texts via embedder.

        Returns None if embedder is unavailable.
        """
        if not self._embedder:
            return None
        try:
            vec_a = self._embedder.embed_text(a)
            vec_b = self._embedder.embed_text(b)
            dot = sum(x * y for x, y in zip(vec_a, vec_b))
            na = sum(x * x for x in vec_a) ** 0.5
            nb = sum(x * x for x in vec_b) ** 0.5
            if na == 0 or nb == 0:
                return 0.0
            return max(0.0, min(1.0, dot / (na * nb)))
        except Exception:
            return None

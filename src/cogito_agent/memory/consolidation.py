from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from .memorizer import Memorizer
from .ports import LLMExtractionPort

logger = logging.getLogger(__name__)


def _format_conversation(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = str(m.get("role", "")).upper()
        content = str(m.get("content", "") or "")
        if not content or role in {"TOOL", "SYSTEM"}:
            continue
        ts = str(m.get("created_at", "") or m.get("timestamp", ""))[:16]
        lines.append(f"[{ts}] {role}: {content}")
    return "\n".join(lines)


class ConsolidationService:
    """Post-turn memory consolidation using structured memory_items (Memory v2).

    After each conversation turn:
    1. LLM extraction of history_entries → ``Memorizer.save()`` → memory_items
    2. LLM compression of recent context → RECENT_CONTEXT.md (simplified)
    3. Trim old messages from session (sliding window)

    All LLM calls go through ``LLMExtractionPort``, implemented in the
    ``runtime`` layer — the ``memory`` package never depends on
    ``ModelAdapter`` directly.
    """

    def __init__(
        self,
        memorizer: Memorizer,
        workspace_path: str = "",
        llm_extractor: LLMExtractionPort | None = None,
        *,
        keep_count: int = 20,
    ) -> None:
        self._memorizer = memorizer
        self._workspace_path = workspace_path
        self._llm_extractor = llm_extractor
        self._keep_count = max(4, keep_count)
        self._consolidation_min_new = max(5, self._keep_count // 2)
        self._threshold = self._keep_count + self._consolidation_min_new

        # per-workspace state
        self._last_consolidated: dict[str, int] = {}

    # ── public API ─────────────────────────────────────────────────────

    def after_turn(
        self,
        messages: list[dict[str, Any]],
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        """Must be called after every completed turn.

        Safe to call even when the memorizer or extractor is unavailable —
        all failures are caught and logged.
        """
        prev_count = self._last_consolidated.get(workspace_id, 0)
        latest_count = len(messages)

        # Step 1: LLM extraction + Memorizer write if threshold reached
        try:
            if self._llm_extractor and self._should_consolidate(messages, prev_count):
                self._extract_and_write(messages, prev_count, workspace_id, session_id)
        except Exception:
            logger.exception("Consolidation extraction failed")

        # Step 2: advance counter
        self._last_consolidated[workspace_id] = latest_count

    # ── consolidation decision ────────────────────────────────────────

    def _should_consolidate(
        self, messages: list[dict[str, Any]], prev_count: int
    ) -> bool:
        if not self._llm_extractor:
            return False
        latest = len(messages)
        new_count = latest - prev_count
        return new_count >= self._consolidation_min_new

    @property
    def needs_consolidation(self) -> bool:
        return False  # checked dynamically per workspace via threshold check

    def consolidation_backlog(self, workspace_id: str, message_count: int) -> int:
        prev = self._last_consolidated.get(workspace_id, 0)
        return max(0, message_count - prev)

    # ── synchronous LLM consolidation (called from after_turn) ────────

    def _extract_and_write(
        self,
        messages: list[dict[str, Any]],
        prev_count: int,
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        """Run LLM extraction + Memorizer write synchronously.

        Called from after_turn() when threshold is met.
        Output goes to memory_items table via Memorizer, not to files.
        """
        if not self._llm_extractor:
            return

        window = messages[prev_count:]
        msg_ids = [str(m.get("id", "")) for m in window if m.get("id")]
        if not msg_ids:
            return

        # Step A: LLM extraction (history_entries + pending_items)
        text = _format_conversation(window)

        # Build memory context from active memories for dedup
        memory_context = ""
        try:
            rows = self._memorizer._db.connection.execute(
                "SELECT summary FROM memory_items WHERE status = 'active'"
                " ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
            if rows:
                memory_context = "\n".join(
                    f"- [{r['summary'][:80]}]" for r in rows if r["summary"]
                )
        except Exception:
            pass

        data = self._llm_extractor.extract_memories(text, memory_context)
        if data:
            if data.get("history_entries"):
                for entry in data["history_entries"]:
                    summary = (entry.get("summary") or "").strip()
                    if not summary:
                        continue
                    ew = int(entry.get("emotional_weight", 0) or 0)
                    self._memorizer.save(
                        summary=summary,
                        memory_type="event",
                        workspace_id=workspace_id,
                        source_ref=session_id,
                        emotional_weight=ew,
                    )
            if data.get("pending_items"):
                for item in data["pending_items"]:
                    content = (item.get("content") or "").strip()
                    tag = str(item.get("tag", "general"))
                    if not content:
                        continue
                    mem_type = {
                        "preference": "preference",
                        "profile": "profile",
                        "key_info": "profile",
                        "health_long_term": "profile",
                        "requested_memory": "profile",
                        "correction": "profile",
                        "task": "task",
                        "general": "general",
                    }.get(tag, "general")
                    self._memorizer.save(
                        summary=content,
                        memory_type=mem_type,
                        workspace_id=workspace_id,
                        source_ref=session_id,
                    )

        # Step B: LLM compression of recent context
        compression = self._llm_extractor.compress_context(text)
        if compression:
            self._memorizer.save(
                summary=json.dumps(compression, ensure_ascii=False),
                memory_type="_recent_context",
                workspace_id=workspace_id,
            )

    # ── helpers ───────────────────────────────────────────────────────

    def get_trim_point(self, workspace_id: str, message_count: int) -> int:
        prev = self._last_consolidated.get(workspace_id, 0)
        if prev <= 0:
            return 0
        if message_count > self._keep_count + prev:
            return max(0, message_count - self._keep_count)
        return 0

    def needs_guard_consolidation(
        self, workspace_id: str, message_count: int
    ) -> bool:
        prev = self._last_consolidated.get(workspace_id, 0)
        pending = message_count - prev
        return pending > self._threshold


# ── Memory file sync (.md views) ─────────────────────────────────────


def _format_memory_md(
    rows: list[dict[str, Any]],
) -> str:
    sections: list[str] = []
    sections.append("# Long-term Memory\n")
    sections.append(
        "This file is auto-generated from memory_items. "
        "Edit memory_items via the CLI or API; changes here will be overwritten.\n"
    )

    type_order = ["profile", "preference", "procedure"]
    type_labels = {
        "profile": "## Profile",
        "preference": "## Preferences",
        "procedure": "## Procedures & Rules",
    }

    for mem_type in type_order:
        type_rows = [r for r in rows if r.get("memory_type") == mem_type]
        if not type_rows:
            continue

        sections.append(f"\n{type_labels.get(mem_type, f'## {mem_type}')}\n")
        for r in type_rows:
            summary = str(r.get("summary", "") or "").strip()
            if not summary:
                continue
            updated = str(r.get("updated_at", "") or "")[:10]
            tag = f" ({updated})" if updated else ""
            sections.append(f"- {summary}{tag}")

    return "\n".join(sections) + "\n"


def _format_recent_context_md(
    data: dict[str, list[str]] | None,
) -> str:
    lines: list[str] = []
    lines.append("# Recent Context\n")
    lines.append(
        "This file is auto-generated. "
        "It reflects the compressed recent conversation context.\n"
    )

    if not data:
        return "\n".join(lines) + "\n"

    section_labels = {
        "active_topics": "## Active Topics",
        "user_preferences": "## Recent Preferences",
        "follow_ups": "## Follow-ups",
        "avoidances": "## Avoidances",
        "ongoing_threads": "## Ongoing Threads",
    }

    for key, label in section_labels.items():
        items = data.get(key, [])
        if items:
            lines.append(f"\n{label}")
            for item in items:
                lines.append(f"- {item}")

    return "\n".join(lines) + "\n"


def _sync_memory_md(db: Any, workspace_path: str, workspace_id: str) -> None:
    from .file_io import atomic_write_memory_file

    rows = db.connection.execute(
        "SELECT summary, memory_type, updated_at FROM memory_items"
        " WHERE workspace_id=? AND status='active'"
        " AND memory_type IN ('profile','preference','procedure')"
        " ORDER BY"
        "   CASE memory_type"
        "     WHEN 'profile' THEN 1"
        "     WHEN 'preference' THEN 2"
        "     WHEN 'procedure' THEN 3"
        "     ELSE 4"
        "   END,"
        "   updated_at DESC",
        (workspace_id,),
    ).fetchall()

    content = _format_memory_md([dict(r) for r in rows])
    atomic_write_memory_file(workspace_path, "MEMORY.md", content)


def _sync_recent_context_md(db: Any, workspace_path: str, workspace_id: str) -> None:
    import json as _json

    from .file_io import atomic_write_memory_file

    row = db.connection.execute(
        "SELECT summary FROM memory_items"
        " WHERE workspace_id=? AND status='active'"
        " AND memory_type='_recent_context'"
        " ORDER BY updated_at DESC LIMIT 1",
        (workspace_id,),
    ).fetchone()

    data: dict[str, list[str]] | None = None
    if row and row["summary"]:
        try:
            data = _json.loads(str(row["summary"]))
        except Exception:
            pass

    content = _format_recent_context_md(data)
    atomic_write_memory_file(workspace_path, "RECENT_CONTEXT.md", content)

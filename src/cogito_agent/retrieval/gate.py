from __future__ import annotations

from dataclasses import dataclass

from .query import MemoryQueryContext


@dataclass
class RetrievalGateResult:
    mode: str = "search"
    degraded_reason: str = ""
    original_query: str = ""
    enriched_query: str = ""


class RetrievalGate:
    """Minimal gate — catches only degenerate cases. Everything else searches.

    Earlier versions used keyword rules (greeting, profile, temporal markers)
    to switch between retrieval modes (profile_only / timeline / resident_only).
    This was brittle, language-dependent, and error-prone.

    The current design always runs hybrid (sparse + dense) retrieval with a
    context-enriched query.  The fusion scorer naturally handles what the
    keyword rules tried to guess:
      - greeting with no relevant memories → all scores below threshold → empty
      - "what did I say about project X"  → FTS5 + embedding match → surfacing
      - "I like ..."                      → semantic match on profile memories → high fusion
    Resident (pinned) memories are always appended after dynamic retrieval,
    so profile/preference context is never lost.
    """

    def evaluate(self, ctx: MemoryQueryContext) -> RetrievalGateResult:
        message = ctx.current_message.strip()

        if not message:
            return RetrievalGateResult(
                mode="skip",
                original_query=ctx.original_query,
                enriched_query=ctx.context_enriched_query,
            )

        enriched = self._enrich_query(ctx)

        return RetrievalGateResult(
            mode="search",
            original_query=ctx.original_query or ctx.current_message,
            enriched_query=enriched,
        )

    def _enrich_query(self, ctx: MemoryQueryContext) -> str:
        """Augment the raw query with session context for better retrieval.

        Fusion scoring will weight results by recency, confidence, and type,
        so adding nearby context helps the sparse/dense matchers find what
        the user is referring to without brittle keyword heuristics.
        """
        parts: list[str] = [ctx.current_message]

        for recent in ctx.recent_user_messages[-2:]:
            text = recent.strip()
            if text and text not in parts:
                parts.append(text)

        if ctx.session_topic_summary:
            summary = ctx.session_topic_summary.strip()
            if summary and summary not in parts:
                parts.append(summary)

        return " ".join(parts)

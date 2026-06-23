from __future__ import annotations

from typing import Any, Protocol


class LLMExtractionPort(Protocol):
    """Model-call interface for memory extraction and context compression.

    Implemented in the runtime layer so that ``memory`` does not depend on
    ``cogito_agent.models`` directly.  The composition root wires the
    concrete implementation into ``ConsolidationService``.
    """

    def extract_memories(
        self,
        conversation_text: str,
        memory_context: str = "",
    ) -> dict[str, Any] | None:
        """Extract structured memory entries from a conversation window.

        Returns a dict with ``history_entries`` and ``pending_items`` keys,
        or ``None`` on failure.
        """
        ...

    def compress_context(
        self,
        conversation_text: str,
    ) -> dict[str, list[str]] | None:
        """Compress a conversation window into structured recent-context fields.

        Returns a dict with keys ``active_topics``, ``user_preferences``,
        ``follow_ups``, ``avoidances``, ``ongoing_threads``,
        or ``None`` on failure.
        """
        ...

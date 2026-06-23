from __future__ import annotations

import json
import logging

from cogito_agent.shared.context_item import ContextItem

from .database import Database

logger = logging.getLogger(__name__)


class SqliteContextTraceSink:
    """Persist context evidence without coupling ContextEngine to SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def persist_context_items(
        self,
        items: list[ContextItem],
        *,
        trace_id: str,
        workspace_id: str,
    ) -> None:
        try:
            with self._db.connection:
                self._db.connection.executemany(
                    "INSERT INTO context_items"
                    " (id, trace_id, workspace_id, source_type, source_id, rank,"
                    " token_estimate, included, reason, freshness_score, trust_score,"
                    " evidence_json, stable_ref, exclusion_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            item.id,
                            trace_id,
                            workspace_id,
                            item.source_type,
                            item.source_id,
                            item.rank,
                            item.token_estimate,
                            1 if item.included else 0,
                            item.reason,
                            item.freshness_score,
                            item.trust_score,
                            json.dumps(item.evidence),
                            item.stable_ref,
                            item.exclusion_reason,
                        )
                        for item in items
                    ],
                )
        except Exception:
            logger.exception("Failed to persist context trace evidence")

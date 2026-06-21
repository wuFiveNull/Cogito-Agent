from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)


_RESIDENT_ELIGIBLE_TYPES = {"profile", "preference", "relationship"}
_RESIDENT_RECENCY_HALF_LIFE_DAYS = 90.0


class ResidentMemorySelector:
    def __init__(self, db: Database) -> None:
        self._db = db

    def select(
        self,
        workspace_id: str,
        token_budget: int = 500,
        type_policy: dict[str, Any] | None = None,
    ) -> list[dict[str, object]]:
        if type_policy is None:
            type_policy = {}

        rows = self._db.connection.execute(
            "SELECT * FROM memories"
            " WHERE workspace_id = ? AND deleted_at IS NULL"
            " AND archived_at IS NULL"
            " AND pinned_at IS NOT NULL"
            " ORDER BY confidence DESC, updated_at DESC",
            (workspace_id,),
        ).fetchall()

        candidates: list[dict[str, object]] = []
        for r in rows:
            mem = dict(r)
            mem_type = str(mem.get("type", "general"))
            policy = type_policy.get(mem_type, {})
            if isinstance(policy, dict):
                resident_eligible = policy.get("resident_eligible", False)
            elif hasattr(policy, "resident_eligible"):
                resident_eligible = policy.resident_eligible
            else:
                resident_eligible = False

            if mem_type in _RESIDENT_ELIGIBLE_TYPES or resident_eligible:
                candidates.append(mem)

        candidates.sort(key=self._resident_score, reverse=True)

        selected: list[dict[str, object]] = []
        used_tokens = 0
        type_counts: dict[str, int] = {}

        for mem in candidates:
            mem_type = str(mem.get("type", "general"))
            policy = type_policy.get(mem_type, {})
            max_items = 99
            if isinstance(policy, dict):
                max_items = policy.get("max_items", 99)
            elif hasattr(policy, "max_items"):
                max_items = policy.max_items

            if type_counts.get(mem_type, 0) >= max_items:
                continue

            text = str(mem.get("text", ""))
            token_est = len(text) // 4
            if used_tokens + token_est > token_budget:
                continue

            selected.append(mem)
            used_tokens += token_est
            type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

        return selected

    @staticmethod
    def _resident_score(mem: dict[str, object]) -> float:
        """Compute a normalized [0, ~2] relevance score for resident memories.

        Uses the same signal blend as the retrieval system (confidence +
        recency + type priority) but without the arbitrary 10x/0.01 constants
        that the old formula used.
        """
        confidence = 0.5
        raw_conf = mem.get("confidence", 0.5)
        if isinstance(raw_conf, (int, float)):
            confidence = max(0.0, min(1.0, float(raw_conf)))

        recency = 0.0
        raw_updated = mem.get("updated_at") or mem.get("created_at") or ""
        try:
            if isinstance(raw_updated, str) and raw_updated:
                dt = datetime.fromisoformat(raw_updated)
                now = datetime.now(UTC)
                age_days = (
                    now - dt.replace(tzinfo=UTC) if dt.tzinfo is None else (now - dt)
                ).total_seconds() / 86400.0
                age_days = max(0.0, age_days)
                recency = math.exp(-math.log(2) * age_days / _RESIDENT_RECENCY_HALF_LIFE_DAYS)
        except (ValueError, TypeError):
            pass

        mem_type = str(mem.get("type", "general"))
        type_priority = {
            "profile": 1.0,
            "preference": 0.9,
            "relationship": 0.8,
            "task": 0.7,
            "project": 0.6,
            "episodic": 0.4,
            "skill": 0.3,
            "general": 0.2,
        }.get(mem_type, 0.2)

        # Blend: confidence + recency are both [0,1], type_priority adds at most 1.0
        return confidence * 0.5 + recency * 0.3 + type_priority * 0.2

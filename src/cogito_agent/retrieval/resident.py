from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)


_RESIDENT_ELIGIBLE_TYPES = {"profile", "preference", "relationship"}


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
        score = 0.0
        raw_conf = mem.get("confidence", 0.5)
        if isinstance(raw_conf, (int, float)):
            score += float(raw_conf) * 10.0

        raw_updated = mem.get("updated_at") or mem.get("created_at") or ""
        try:
            if isinstance(raw_updated, str) and raw_updated:
                dt = datetime.fromisoformat(raw_updated)
                now = datetime.now(UTC)
                age_hours = (now - dt.replace(tzinfo=UTC) if dt.tzinfo is None
                             else (now - dt)).total_seconds() / 3600.0
                score -= age_hours * 0.01
        except (ValueError, TypeError):
            pass

        mem_type = str(mem.get("type", "general"))
        type_order = {"profile": 50, "preference": 40, "relationship": 30,
                      "task": 20, "project": 15, "episodic": 10, "skill": 5, "general": 1}
        score += type_order.get(mem_type, 1)

        return score

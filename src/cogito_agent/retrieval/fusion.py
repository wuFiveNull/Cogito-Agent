from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ScoreBreakdown:
    dense_score: float = 0.0
    sparse_score: float = 0.0
    recency_score: float = 0.0
    confidence_score: float = 0.0
    task_relevance_score: float = 0.0
    type_priority_score: float = 0.0
    final_score: float = 0.0


_TYPE_PRIORITY_MAP: dict[str, float] = {
    "profile": 1.0,
    "preference": 0.9,
    "relationship": 0.8,
    "task": 0.7,
    "project": 0.6,
    "episodic": 0.4,
    "skill": 0.3,
    "general": 0.2,
}


def _compute_recency_score(mem: dict[str, object], half_life_days: float = 90.0) -> float:
    raw_updated = mem.get("updated_at") or mem.get("created_at") or ""
    try:
        if isinstance(raw_updated, str) and raw_updated:
            dt = datetime.fromisoformat(raw_updated)
            now = datetime.now(UTC)
            age_days = (now - dt.replace(tzinfo=UTC) if dt.tzinfo is None
                        else (now - dt)).total_seconds() / 86400.0
            age_days = max(0.0, age_days)
            return math.exp(-math.log(2) * age_days / half_life_days)
    except (ValueError, TypeError):
        pass
    return 0.0


def _compute_confidence_score(mem: dict[str, object]) -> float:
    raw = mem.get("confidence", 0.5)
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return 0.5


def _compute_type_priority_score(mem: dict[str, object]) -> float:
    mem_type = str(mem.get("type", "general"))
    return _TYPE_PRIORITY_MAP.get(mem_type, 0.2)


def _compute_task_relevance_score(
    mem: dict[str, object], query: str,
) -> float:
    if not query:
        return 0.0
    text = str(mem.get("text", ""))
    query_lower = query.lower()
    text_lower = text.lower()
    score = 0.0

    if query_lower in text_lower:
        score += 0.5

    query_words = set(query_lower.split())
    text_words = set(text_lower.split())
    overlap = len(query_words & text_words)
    if overlap > 0:
        score += min(overlap / max(len(query_words), 1), 1.0) * 0.5

    return min(score, 1.0)


class CandidateFusion:
    def __init__(
        self,
        dense_weight: float = 0.35,
        sparse_weight: float = 0.30,
        recency_weight: float = 0.10,
        confidence_weight: float = 0.10,
        task_relevance_weight: float = 0.10,
        type_priority_weight: float = 0.05,
        recency_half_life_days: float = 90.0,
    ) -> None:
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight
        self._recency_weight = recency_weight
        self._confidence_weight = confidence_weight
        self._task_relevance_weight = task_relevance_weight
        self._type_priority_weight = type_priority_weight
        self._recency_half_life_days = recency_half_life_days

    def fuse(
        self,
        sparse_candidates: list[dict[str, object]],
        dense_candidates: list[dict[str, object]],
        query: str = "",
    ) -> list[tuple[dict[str, object], ScoreBreakdown]]:
        merged: dict[str, tuple[dict[str, object], ScoreBreakdown, int]] = {}

        for mem in sparse_candidates:
            mid = str(mem.get("id", ""))
            breakdown = ScoreBreakdown()
            raw_sparse = mem.get("sparse_score", 0.0)
            breakdown.sparse_score = raw_sparse if isinstance(raw_sparse, (int, float)) else 0.0
            merged[mid] = (mem, breakdown, 0)

        for mem in dense_candidates:
            mid = str(mem.get("id", ""))
            raw_dense = mem.get("dense_score", 0.0)
            dense_score = raw_dense if isinstance(raw_dense, (int, float)) else 0.0
            if mid in merged:
                _, breakdown, _ = merged[mid]
                breakdown.dense_score = dense_score
            else:
                breakdown = ScoreBreakdown()
                breakdown.dense_score = dense_score
                merged[mid] = (mem, breakdown, 0)

        results: list[tuple[dict[str, object], ScoreBreakdown]] = []
        for mem, breakdown, _ in merged.values():
            breakdown.recency_score = _compute_recency_score(
                mem, self._recency_half_life_days,
            )
            breakdown.confidence_score = _compute_confidence_score(mem)
            breakdown.task_relevance_score = _compute_task_relevance_score(mem, query)
            breakdown.type_priority_score = _compute_type_priority_score(mem)

            breakdown.final_score = (
                self._dense_weight * breakdown.dense_score
                + self._sparse_weight * breakdown.sparse_score
                + self._recency_weight * breakdown.recency_score
                + self._confidence_weight * breakdown.confidence_score
                + self._task_relevance_weight * breakdown.task_relevance_score
                + self._type_priority_weight * breakdown.type_priority_score
            )

            results.append((mem, breakdown))

        results.sort(key=lambda x: x[1].final_score, reverse=True)
        return results

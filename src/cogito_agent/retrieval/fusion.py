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
    final_score: float = 0.0  # RRF score for ranking (rank-based, not absolute relevance)
    semantic_score: float = 0.0  # max(dense, sparse) for threshold/filtering
    hotness_score: float = 0.0  # confidence * recency decay for frequently-used boost


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
            age_days = (
                now - dt.replace(tzinfo=UTC) if dt.tzinfo is None else (now - dt)
            ).total_seconds() / 86400.0
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
    mem: dict[str, object],
    query: str,
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


def _hit_id(item: dict[str, object]) -> str:
    return str(item.get("id", "") or item.get("memory_id", "") or "")


def _hit_score(item: dict[str, object]) -> float:
    """Best-effort score extraction — used only for tiebreaking, not ranking."""
    raw = item.get("sparse_score") or item.get("dense_score") or 0.0
    return float(raw) if isinstance(raw, (int, float)) else 0.0


class CandidateFusion:
    """Fuse sparse and dense candidates using Reciprocal Rank Fusion (RRF).

    RRF is rank-based, not score-based — it doesn't care about absolute
    score magnitudes or whether two scorers use different scales. This
    replaces the old weighted-sum approach which required brittle tuning
    of 6 fixed weights.

    Design follows Akashic's memory2/retriever.py pattern:
    RRF with configurable k and keyword weight.
    """

    def __init__(
        self,
        rrf_k: float = 60.0,
        keyword_weight: float = 0.5,
        recency_half_life_days: float = 90.0,
        hotness_alpha: float = 0.0,
    ) -> None:
        self._rrf_k = rrf_k
        self._keyword_weight = keyword_weight
        self._recency_half_life_days = recency_half_life_days
        self._hotness_alpha = hotness_alpha

    def fuse(
        self,
        sparse_candidates: list[dict[str, object]],
        dense_candidates: list[dict[str, object]],
        query: str = "",
    ) -> list[tuple[dict[str, object], ScoreBreakdown]]:
        # ── 1. Build rank maps ──
        # Dense candidates sorted by dense_score descending → rank 1 = best
        dense_sorted = sorted(
            dense_candidates,
            key=lambda x: float(x.get("dense_score", 0.0) or 0.0),
            reverse=True,
        )
        dense_rank: dict[str, int] = {}
        for rank, item in enumerate(dense_sorted, 1):
            mid = _hit_id(item)
            if mid:
                dense_rank.setdefault(mid, rank)

        # Sparse candidates sorted by sparse_score descending → rank 1 = best
        sparse_sorted = sorted(
            sparse_candidates,
            key=lambda x: float(x.get("sparse_score", 0.0) or 0.0),
            reverse=True,
        )
        kw_rank: dict[str, int] = {}
        for rank, item in enumerate(sparse_sorted, 1):
            mid = _hit_id(item)
            if mid:
                kw_rank.setdefault(mid, rank)

        # ── 2. Build unified item map (merge fields from both channels) ──
        merged: dict[str, dict[str, object]] = {}
        for item in sparse_candidates:
            mid = _hit_id(item)
            if mid:
                merged[mid] = dict(item)
        for item in dense_candidates:
            mid = _hit_id(item)
            if mid:
                if mid in merged:
                    # Keep sparse fields, add dense-only fields
                    for key in ("dense_score", "dense_rank"):
                        if key in item:
                            merged[mid][key] = item[key]
                else:
                    merged[mid] = dict(item)

        # ── 3. RRF scoring ──
        results: list[tuple[dict[str, object], ScoreBreakdown]] = []
        for mid, item in merged.items():
            rrf = 0.0
            if mid in dense_rank:
                rrf += 1.0 / (self._rrf_k + dense_rank[mid])
            if mid in kw_rank:
                rrf += self._keyword_weight / (self._rrf_k + kw_rank[mid])

            dense_score = float(item.get("dense_score", 0.0) or 0.0)
            sparse_score = float(item.get("sparse_score", 0.0) or 0.0)
            recency_score = _compute_recency_score(item, self._recency_half_life_days)
            confidence_score = _compute_confidence_score(item)
            task_relevance_score = _compute_task_relevance_score(item, query)
            type_priority_score = _compute_type_priority_score(item)

            # Hotness: confidence-weighted recency — frequently-accessed,
            # high-confidence memories get a ranking boost.
            hotness_score = confidence_score * recency_score

            # Blend: RRF base + hotness boost (when hotness_alpha > 0)
            if self._hotness_alpha > 0:
                rrf_boosted = rrf * (1.0 + self._hotness_alpha * hotness_score)
            else:
                rrf_boosted = rrf

            # threshold uses best available relevance signal
            semantic_score = max(
                dense_score,
                sparse_score,
                task_relevance_score * 0.5,
                recency_score * 0.3,
            )

            breakdown = ScoreBreakdown(
                dense_score=dense_score,
                sparse_score=sparse_score,
                recency_score=recency_score,
                confidence_score=confidence_score,
                task_relevance_score=task_relevance_score,
                type_priority_score=type_priority_score,
                final_score=rrf_boosted,
                semantic_score=semantic_score,
                hotness_score=hotness_score,
            )
            item["_rrf_score"] = rrf_boosted
            results.append((item, breakdown))

        # ── 4. Sort by RRF score descending, tiebreak by individual score ──
        results.sort(key=lambda x: (x[1].final_score, _hit_score(x[0])), reverse=True)
        return results

from __future__ import annotations

import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from cogito_agent.storage import Database

from ..embedding.interface import EmbeddingProvider
from .dense import DenseMemoryRetriever
from .fusion import CandidateFusion
from .gate import RetrievalGate, RetrievalGateResult
from .query import MemoryQueryBuilder, MemoryQueryContext
from .resident import ResidentMemorySelector
from .sparse import SparseMemoryRetriever

logger = logging.getLogger(__name__)


class HealthState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class RetrievalMode(str, enum.Enum):
    HYBRID = "hybrid"
    SPARSE_ONLY = "sparse_only"
    DENSE_ONLY = "dense_only"
    RESIDENT_ONLY = "resident_only"
    NO_RECALL = "no_recall"
    PROFILE_ONLY = "profile_only"
    TIMELINE = "timeline"
    DEGRADED = "degraded"


_DEGRADED_REASON_CODES: dict[str, str] = {
    "embedding_secret_missing": "Embedding API key not configured",
    "embedding_auth_failed": "Embedding API authentication failed",
    "embedding_rate_limited": "Embedding API rate limited",
    "embedding_timeout": "Embedding API timed out",
    "embedding_api_error": "Embedding API returned an error",
    "embedding_dimension_mismatch": "Embedding dimension mismatch",
    "embedding_invalid_response": "Embedding API returned invalid response",
    "dense_provider_not_configured": "Dense provider not configured",
    "embedding_all_failed": "All embedding attempts failed",
}


def _code_to_reason(code: str) -> str:
    return _DEGRADED_REASON_CODES.get(code, code)


@dataclass
class MemoryRecallResult:
    resident_memories: list[dict[str, object]] = field(default_factory=list)
    dynamic_memories: list[dict[str, object]] = field(default_factory=list)
    mode: str = "hybrid"
    gate_mode: str = ""
    health_state: str = "healthy"
    degraded_reason: str = ""
    degraded_code: str = ""
    sparse_candidate_count: int = 0
    dense_candidate_count: int = 0
    union_candidate_count: int = 0
    selected_count: int = 0
    excluded_count: int = 0
    resident_count: int = 0
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 0
    embedding_version: str = "2"
    trace_id: str = ""
    score_breakdowns: dict[str, dict[str, float]] = field(default_factory=dict)
    excluded: list[dict[str, str]] = field(default_factory=list)
    latencies: dict[str, float] = field(default_factory=dict)

    def to_legacy_result(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for mem in self.resident_memories:
            entry = dict(mem)
            entry["retrieval_source"] = "resident"
            result.append(entry)
        for mem in self.dynamic_memories:
            entry = dict(mem)
            entry["retrieval_source"] = "dynamic"
            result.append(entry)
        return result


class MemoryRetrievalService:
    def __init__(
        self,
        db: Database,
        provider: EmbeddingProvider | None = None,
        sparse_retriever: SparseMemoryRetriever | None = None,
        dense_retriever: DenseMemoryRetriever | None = None,
        query_builder: MemoryQueryBuilder | None = None,
        gate: RetrievalGate | None = None,
        resident_selector: ResidentMemorySelector | None = None,
        fusion: CandidateFusion | None = None,
        retrieval_config: Any = None,
    ) -> None:
        self._db = db
        self._sparse = sparse_retriever or SparseMemoryRetriever(db)
        self._dense = dense_retriever or DenseMemoryRetriever(db, provider)
        self._query_builder = query_builder or MemoryQueryBuilder()
        self._gate = gate or RetrievalGate()
        self._resident = resident_selector or ResidentMemorySelector(db)
        self._fusion = fusion or CandidateFusion()
        self._config = retrieval_config

    @property
    def provider(self) -> EmbeddingProvider | None:
        return self._dense.provider

    @provider.setter
    def provider(self, p: EmbeddingProvider | None) -> None:
        self._dense.provider = p

    def _finalize(
        self, result: MemoryRecallResult, ctx: MemoryQueryContext, t0: float,
    ) -> MemoryRecallResult:
        result.latencies["total"] = (time.time() - t0) * 1000
        result.excluded_count = len(result.excluded)
        try:
            self._persist_trace(result, ctx)
        except Exception as e:
            logger.warning("Failed to persist retrieval trace: %s", e)
        return result

    def recall(
        self,
        query_context: MemoryQueryContext,
        limit: int = 10,
        include_archived: bool = False,
        force_mode: str = "",
    ) -> MemoryRecallResult:
        trace_id = str(uuid.uuid4())
        result = MemoryRecallResult(trace_id=trace_id)
        result.embedding_provider = (
            self._dense.provider.provider_name if self._dense.provider else ""
        )
        result.embedding_model = (
            self._dense.provider.model_name if self._dense.provider else ""
        )
        result.embedding_dimension = (
            self._dense.provider.dimension if self._dense.provider else 0
        )

        if force_mode:
            result.mode = force_mode
            result.gate_mode = force_mode
            gate_result = RetrievalGateResult(
                mode=force_mode,
                original_query=query_context.original_query,
                enriched_query=query_context.context_enriched_query,
            )
        else:
            gate_result = self._gate.evaluate(query_context)
            result.mode = gate_result.mode
            result.gate_mode = gate_result.mode

        config = self._get_config()
        type_policy = config.get("type_policy", {})
        dense_candidate_limit = config.get("dense_candidate_limit", 40)
        sparse_candidate_limit = config.get("sparse_candidate_limit", 40)
        resident_budget = config.get("resident_token_budget", 500)
        dynamic_budget = config.get("dynamic_token_budget", 1000)
        min_score = config.get("min_final_score", 0.20)

        query = query_context.context_enriched_query or query_context.current_message
        t0 = time.time()

        # ── no_recall: absolutely nothing ──
        if gate_result.mode == "no_recall":
            return self._finalize(result, query_context, t0)

        # ── profile_only: only profile/preference resident ──
        if gate_result.mode == "profile_only":
            profile_policy = {
                k: v for k, v in type_policy.items()
                if k in ("profile", "preference")
            }
            result.resident_memories = self._resident.select(
                query_context.workspace_id, resident_budget, profile_policy,
            )
            result.resident_count = len(result.resident_memories)
            return self._finalize(result, query_context, t0)

        # ── resident_only: only resident memories ──
        if gate_result.mode == "resident_only":
            result.resident_memories = self._resident.select(
                query_context.workspace_id, resident_budget, type_policy,
            )
            result.resident_count = len(result.resident_memories)
            return self._finalize(result, query_context, t0)

        # ── dynamic retrieval (sparse, hybrid, timeline) ──
        result.health_state = "healthy"
        use_sparse = gate_result.mode in ("sparse", "hybrid", "timeline")
        use_dense = gate_result.mode in ("hybrid", "timeline")

        sparse_candidates: list[dict[str, object]] = []
        dense_candidates: list[dict[str, object]] = []

        if use_sparse:
            try:
                t1 = time.time()
                sparse_candidates = self._sparse.search(
                    query_context.workspace_id, query,
                    limit=sparse_candidate_limit,
                    include_archived=include_archived,
                )
                result.latencies["sparse"] = (time.time() - t1) * 1000
            except Exception as e:
                logger.warning("Sparse retrieval failed: %s", e)
                sparse_candidates = []

        dense_attempted = False
        if use_dense:
            if self._dense.provider is None:
                result.health_state = "disabled"
                result.mode = "sparse_only"
                result.degraded_code = "dense_provider_not_configured"
                result.degraded_reason = _code_to_reason("dense_provider_not_configured")
            elif not self._dense.provider.is_semantic:
                result.health_state = "disabled"
                result.mode = "sparse_only"
            else:
                dense_attempted = True
                try:
                    t1 = time.time()
                    dense_candidates = self._dense.search(
                        query_context.workspace_id, query,
                        limit=dense_candidate_limit,
                        include_archived=include_archived,
                    )
                    result.latencies["dense"] = (time.time() - t1) * 1000
                except Exception as e:
                    result.health_state = "degraded"
                    if result.mode != "degraded":
                        result.mode = "degraded"
                    result.degraded_code = "embedding_api_error"
                    result.degraded_reason = _code_to_reason("embedding_api_error")
                    dense_candidates = []

        result.sparse_candidate_count = len(sparse_candidates)
        result.dense_candidate_count = len(dense_candidates)

        if result.health_state == "healthy" and not use_dense:
            result.mode = "sparse_only"
        elif result.health_state == "healthy" and not dense_candidates and dense_attempted:
            result.mode = "sparse_only"
        elif result.health_state == "healthy" and not sparse_candidates and dense_candidates:
            result.mode = "dense_only"

        if not sparse_candidates and not dense_candidates:
            return self._finalize(result, query_context, t0)

        fused = self._fusion.fuse(sparse_candidates, dense_candidates, query)
        result.union_candidate_count = len(fused)

        selected: list[dict[str, object]] = []
        type_counts: dict[str, int] = {}
        score_breakdowns: dict[str, dict[str, float]] = {}
        excluded: list[dict[str, str]] = []
        used_tokens = 0

        for mem, breakdown in fused:
            mid = str(mem.get("id", ""))
            mem_type = str(mem.get("type", "general"))

            policy = type_policy.get(mem_type, {})
            if isinstance(policy, dict):
                threshold = policy.get("threshold", min_score)
                max_items = policy.get("max_items", 99)
            else:
                threshold = getattr(policy, "threshold", min_score)
                max_items = getattr(policy, "max_items", 99)

            if breakdown.final_score < threshold:
                excluded.append({"memory_id": mid, "reason": "below_threshold"})
                continue

            if type_counts.get(mem_type, 0) >= max_items:
                excluded.append({"memory_id": mid, "reason": "type_quota", "type": mem_type})
                continue

            token_est = max(1, len(str(mem.get("text", ""))) // 4)
            if used_tokens + token_est > dynamic_budget:
                excluded.append({"memory_id": mid, "reason": "token_budget"})
                continue

            score_breakdowns[mid] = {
                "dense_score": breakdown.dense_score,
                "sparse_score": breakdown.sparse_score,
                "recency_score": breakdown.recency_score,
                "confidence_score": breakdown.confidence_score,
                "task_relevance_score": breakdown.task_relevance_score,
                "type_priority_score": breakdown.type_priority_score,
                "final_score": breakdown.final_score,
            }

            entry = dict(mem)
            entry["_score_breakdown"] = score_breakdowns[mid]
            entry["retrieval_source"] = "dynamic"
            selected.append(entry)
            type_counts[mem_type] = type_counts.get(mem_type, 0) + 1
            used_tokens += token_est

            if len(selected) >= limit:
                break

        result.dynamic_memories = selected
        result.selected_count = len(selected)
        result.score_breakdowns = score_breakdowns
        result.excluded = excluded

        # Resident selection (adds to result, does not replace)
        try:
            resident = self._resident.select(
                query_context.workspace_id, resident_budget, type_policy,
            )
            existing_ids = {str(m.get("id", "")) for m in selected}
            for mem in resident:
                if str(mem.get("id", "")) not in existing_ids:
                    mem["retrieval_source"] = "resident"
                    result.resident_memories.append(mem)
            result.resident_count = len(result.resident_memories)
        except Exception as e:
            logger.warning("Resident selection failed: %s", e)

        return self._finalize(result, query_context, t0)

    def _persist_trace(
        self, result: MemoryRecallResult, ctx: MemoryQueryContext,
    ) -> None:
        rt_id = result.trace_id or str(uuid.uuid4())
        try:
            self._db.connection.execute(
                "INSERT INTO retrieval_traces"
                " (id, workspace_id, session_id, gate_mode, original_query,"
                "  enriched_query, retrieval_mode, degraded_reason,"
                "  sparse_candidate_count, dense_candidate_count,"
                "  union_candidate_count, selected_count, resident_count,"
                "  embedding_provider, embedding_model, embedding_dimension,"
                "  embedding_version, sparse_latency_ms, dense_latency_ms,"
                "  total_latency_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rt_id, ctx.workspace_id, ctx.session_id,
                    result.gate_mode, ctx.original_query,
                    ctx.context_enriched_query, result.mode,
                    result.degraded_reason,
                    result.sparse_candidate_count, result.dense_candidate_count,
                    result.union_candidate_count, result.selected_count,
                    result.resident_count,
                    result.embedding_provider, result.embedding_model,
                    result.embedding_dimension, result.embedding_version,
                    result.latencies.get("sparse", 0.0),
                    result.latencies.get("dense", 0.0),
                    result.latencies.get("total", 0.0),
                ),
            )

            for mem in result.dynamic_memories:
                mid = str(mem.get("id", ""))
                bd = result.score_breakdowns.get(mid, {})
                self._db.connection.execute(
                    "INSERT INTO retrieval_trace_results"
                    " (id, trace_id, memory_id, sparse_score, dense_score,"
                    "  recency_score, confidence_score, task_relevance_score,"
                    "  type_priority_score, final_score, inclusion_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()), rt_id, mid,
                        bd.get("sparse_score", 0.0), bd.get("dense_score", 0.0),
                        bd.get("recency_score", 0.0), bd.get("confidence_score", 0.0),
                        bd.get("task_relevance_score", 0.0),
                        bd.get("type_priority_score", 0.0),
                        bd.get("final_score", 0.0), "dynamic",
                    ),
                )

            for entry in result.excluded:
                eid = entry.get("memory_id", "")
                if eid:
                    self._db.connection.execute(
                        "INSERT INTO retrieval_trace_results"
                        " (id, trace_id, memory_id, final_score, excluded_reason)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            str(uuid.uuid4()), rt_id, eid,
                            float(entry.get("score", 0.0)),
                            entry.get("reason", ""),
                        ),
                    )

            self._db.connection.commit()
        except Exception as e:
            logger.warning("Failed to write retrieval trace rows: %s", e)

    def search_compat(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
        recent_user_messages: list[str] | None = None,
    ) -> list[dict[str, object]]:
        ctx = self._query_builder.build(
            current_message=query,
            recent_user_messages=recent_user_messages,
            workspace_id=workspace_id,
        )
        recall_result = self.recall(
            ctx, limit=limit, include_archived=include_archived,
            force_mode="hybrid",
        )
        results = recall_result.to_legacy_result()
        trace_id = recall_result.trace_id
        mode = recall_result.mode
        for r in results:
            r["_retrieval_trace_id"] = trace_id
            r["_retrieval_mode"] = mode
        return results

    def _get_config(self) -> dict[str, Any]:
        if self._config is not None:
            if hasattr(self._config, "model_dump"):
                result = self._config.model_dump()
                return result if isinstance(result, dict) else {}
            if hasattr(self._config, "type_policy"):
                cfg = {}
                for k in dir(self._config):
                    if not k.startswith("_"):
                        cfg[k] = getattr(self._config, k)
                return cfg
            return dict(self._config)
        return {}

    def explain_search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        recent_user_messages: list[str] | None = None,
    ) -> dict[str, Any]:
        ctx = self._query_builder.build(
            current_message=query,
            recent_user_messages=recent_user_messages,
            workspace_id=workspace_id,
        )
        result = self.recall(ctx, limit=limit)
        return {
            "trace_id": result.trace_id,
            "mode": result.mode,
            "gate_mode": result.gate_mode,
            "health_state": result.health_state,
            "degraded_code": result.degraded_code,
            "degraded_reason": result.degraded_reason,
            "sparse_candidate_count": result.sparse_candidate_count,
            "dense_candidate_count": result.dense_candidate_count,
            "union_candidate_count": result.union_candidate_count,
            "selected_count": result.selected_count,
            "resident_count": result.resident_count,
            "embedding_provider": result.embedding_provider,
            "embedding_model": result.embedding_model,
            "embedding_dimension": result.embedding_dimension,
            "score_breakdowns": result.score_breakdowns,
            "latencies_ms": result.latencies,
            "excluded": result.excluded,
            "selected": [
                {
                    "id": str(m.get("id", "")),
                    "text": str(m.get("text", ""))[:100],
                    "type": str(m.get("type", "general")),
                    "source": m.get("retrieval_source", "dynamic"),
                }
                for m in result.dynamic_memories + result.resident_memories
            ],
        }


def create_retrieval_service(
    db: Any,
    config: Any = None,
    secrets_provider: Any = None,
    embedding_provider: Any | None = None,
) -> MemoryRetrievalService:
    """Unified composition root for the retrieval stack.

    Accepts either a pre-built embedding_provider or creates one from config.
    Every caller (CLI, API, RuntimeKernel) must use this factory so that
    the HTTP client, secrets, and config are wired exactly once.
    """
    from cogito_agent.embedding.service import create_embedding_provider_from_config as _make_provider
    from cogito_agent.retrieval.dense import DenseMemoryRetriever
    from cogito_agent.retrieval.sparse import SparseMemoryRetriever

    if embedding_provider is None and config is not None:
        emb_cfg = getattr(config, "embedding", None) or config
        embedding_provider = _make_provider(emb_cfg, secrets_provider=secrets_provider)

    cfg = None
    fusion = None
    if config is not None:
        retrieval_cfg = getattr(config, "retrieval", None)
        if retrieval_cfg is not None:
            cfg = retrieval_cfg
            w = retrieval_cfg.weights
            fusion = CandidateFusion(
                dense_weight=w.dense,
                sparse_weight=w.sparse,
                recency_weight=w.recency,
                confidence_weight=w.confidence,
                task_relevance_weight=w.task_relevance,
                type_priority_weight=w.type_priority,
                recency_half_life_days=retrieval_cfg.recency_half_life_days,
            )

    return MemoryRetrievalService(
        db=db,
        provider=embedding_provider,
        sparse_retriever=SparseMemoryRetriever(db),
        dense_retriever=DenseMemoryRetriever(db, embedding_provider),
        fusion=fusion,
        retrieval_config=cfg,
    )

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryEditRepository,
    MemoryRepository,
)

from cogito_agent.retrieval import MemoryRetrievalPort

from ..embedding.service import MemoryEmbeddingIndexService



logger = logging.getLogger(__name__)

_TAG_MAP: dict[str, str] = {
    "preference": "preference",
    "profile": "profile",
    "task": "task",
    "fact": "fact",
    "key_info": "key_info",
    "requested_memory": "requested_memory",
    "health_long_term": "health_long_term",
    "correction": "correction",
    "general": "general",
}


class MemoryApplicationService:
    """Unified memory service.

    Provides write (create_candidate_file/edit/correct/delete/merge) and
    search (recall_search) operations for both tool-call and API paths.
    """

    def __init__(
        self,
        db: Database | None = None,
        embedding_index: MemoryEmbeddingIndexService | None = None,
        audit: AuditLogger | None = None,
        retrieval_service: MemoryRetrievalPort | None = None,
    ) -> None:
        self._db = db
        self._embedding_index = embedding_index
        self._audit = audit or AuditLogger(db) if db else None
        self._current_workspace_id: str = ""
        self._current_trace_id: str = ""
        self._retrieval_service = retrieval_service

        # SQLite repos (backward compat for memories)
        if db is not None:
            self._mem_repo = MemoryRepository(db)
            self._edit_repo = MemoryEditRepository(db)

    def set_current_context(self, workspace_id: str, trace_id: str = "") -> None:
        self._current_workspace_id = workspace_id
        self._current_trace_id = trace_id

    # ── SQLite methods (backward compat, keep for Console/API) ──

    def create_memory(
        self,
        workspace_id: str,
        text: str,
        memory_type: str = "general",
        confidence: float = 0.5,
        actor_id: str = "system",
    ) -> dict[str, object]:
        mid = str(uuid.uuid4())
        memory = self._mem_repo.create(mid, workspace_id, text, memory_type)
        self._try_index(mid, text)
        if self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.create",
                resource=f"memory:{mid}",
                workspace_id=workspace_id,
                decision="allow",
                reason=f"type={memory_type}",
            )
        return memory

    def edit_memory(
        self,
        mid: str,
        workspace_id: str,
        new_text: str,
        actor_id: str = "cli",
    ) -> bool:
        old = self._mem_repo.get_by_id(mid, workspace_id)
        if old is None:
            return False
        old_text = str(old.get("text", ""))
        if old_text == new_text:
            return True
        ok = self._mem_repo.edit_text(mid, workspace_id, new_text, actor_id=actor_id)
        if ok:
            self._mark_stale(mid)
            self._try_index(mid, new_text)
            if self._audit:
                self._audit.log(
                    actor_id=actor_id,
                    action="memory.edit",
                    resource=f"memory:{mid}",
                    workspace_id=workspace_id,
                    decision="allow",
                )
        return ok

    def correct_memory(
        self,
        mid: str,
        workspace_id: str,
        new_text: str,
        actor_id: str = "cli",
    ) -> bool:
        old = self._mem_repo.get_by_id(mid, workspace_id)
        if old is None:
            return False
        old_text = str(old.get("text", ""))
        if old_text == new_text:
            return True
        ok = self._mem_repo.correct_text(mid, workspace_id, new_text, actor_id=actor_id)
        if ok:
            self._mark_stale(mid)
            self._try_index(mid, new_text)
        return ok

    def merge_memories(
        self,
        source_mid: str,
        target_mid: str,
        workspace_id: str,
        actor_id: str = "cli",
    ) -> bool:
        ok = self._mem_repo.merge(source_mid, target_mid, workspace_id)
        if ok:
            target = self._mem_repo.get_by_id(target_mid, workspace_id)
            if target:
                self._mark_stale(target_mid)
                self._try_index(target_mid, str(target.get("text", "")))
        return ok

    def archive_memory(
        self,
        mid: str,
        workspace_id: str,
        actor_id: str = "cli",
    ) -> bool:
        ok = self._mem_repo.archive(mid, workspace_id)
        if ok and self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.archive",
                resource=f"memory:{mid}",
                workspace_id=workspace_id,
                decision="allow",
            )
        return ok

    def restore_memory(
        self,
        mid: str,
        workspace_id: str,
        actor_id: str = "cli",
    ) -> bool:
        ok = self._mem_repo.unarchive(mid, workspace_id)
        if ok:
            memory = self._mem_repo.get_by_id(mid, workspace_id)
            if memory and self._embedding_index and self._embedding_index.provider:
                text = str(memory.get("text", ""))
                existing = self._embedding_index._get_existing_embedding(mid)
                if existing is None or existing.get("status") != "ready":
                    self._try_index(mid, text)
        return ok

    def delete_memory(
        self,
        mid: str,
        workspace_id: str,
        actor_id: str = "cli",
    ) -> bool:
        ok = self._edit_repo.hard_delete(mid, workspace_id)
        if ok and self._embedding_index:
            self._embedding_index.delete_or_deactivate(mid)
        if ok and self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.delete",
                resource=f"memory:{mid}",
                workspace_id=workspace_id,
                decision="allow",
            )
        return ok

    def soft_delete_memory(
        self,
        mid: str,
        workspace_id: str,
        actor_id: str = "console",
    ) -> bool:
        if self._mem_repo.get_by_id(mid, workspace_id) is None:
            return False
        self._mem_repo.soft_delete(mid, workspace_id)
        if self._embedding_index:
            self._embedding_index.delete_or_deactivate(mid)
        if self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.delete",
                resource=f"memory:{mid}",
                workspace_id=workspace_id,
                decision="allow",
            )
        return True

    def consolidate_memories(self, workspace_id: str, actor_id: str = "cli") -> int:
        from cogito_agent.memory.maintenance import MemoryMaintenance

        dm = MemoryMaintenance(self._db)
        count = dm.consolidate_legacy_memories(workspace_id)
        if count and self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.consolidate",
                resource="memory",
                workspace_id=workspace_id,
                decision="allow",
                reason=f"removed {count} duplicates",
            )
        return count

    # ── Candidate accept/reject (file-based) ──

    # ── Memorizer-based write (replaces old PENDING.md) ──

    def create_candidate_file(
        self,
        workspace_id: str,
        text: str,
        memory_type: str = "general",
        confidence: float = 0.5,
        session_id: str = "",
        actor_id: str = "assistant",
    ) -> dict[str, object]:
        from .memorizer import Memorizer

        memorizer = Memorizer(self._db)
        content = text.strip()
        if not content:
            return {"id": "", "text": "", "type": memory_type, "error": "empty text"}
        result = memorizer.save(
            summary=content,
            memory_type=memory_type,
            workspace_id=workspace_id,
            source_ref=session_id,
            extra={"confidence": confidence, "source": actor_id},
        )
        if self._audit:
            self._audit.log(
                actor_id=actor_id,
                action="memory.candidate.create",
                resource=f"memory_item:{result.get('id', '')}",
                workspace_id=workspace_id,
                decision="allow",
                reason=f"type={memory_type}, confidence={confidence}",
            )
        return {"id": result.get("id", ""), "text": content, "type": memory_type}

    def recall_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memories using the full hybrid retrieval pipeline.

        Returns results from MemoryRetrievalService (sparse + dense + RRF fusion).
        """
        if self._retrieval_service is None:
            return []
        try:
            from cogito_agent.retrieval.query import MemoryQueryBuilder

            qctx = MemoryQueryBuilder().build(
                current_message=query,
                workspace_id=workspace_id,
            )
            result = self._retrieval_service.recall(qctx, limit=limit)
            memories: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for mem in result.resident_memories + result.dynamic_memories:
                mid = str(mem.get("id", ""))
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    entry = dict(mem)
                    entry["retrieval_source"] = mem.get("retrieval_source", "dynamic")
                    memories.append(entry)
            return memories
        except Exception as e:
            logger.warning("Full retrieval recall failed: %s", e)
            return []

    # ── tool registration ──

    def register_with_capability_registry(
        self,
        cap_reg: object,
    ) -> None:
        from cogito_agent.capability.registry import CapabilityRegistry, ToolResult
        from cogito_agent.shared import (
            CapabilityManifest,
            CapabilityType,
            Permission,
            RiskLevel,
        )

        # ── memory.store_candidate ──

        cand_manifest = CapabilityManifest(
            name="memory.store_candidate",
            version="1.0.0",
            type=CapabilityType.tool,
            description="Store a candidate memory for user review. "
            "Call this when the user expresses a preference, fact about themselves,"
            " task decision, or anything worth remembering long-term.",
            input_schema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "The information to remember (concise summary)",
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "preference", "profile", "task", "fact",
                            "key_info", "requested_memory", "health_long_term",
                            "correction", "general",
                        ],
                        "description": "Category of memory",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Importance (0-1). Higher = more likely worth remembering",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
                "required": ["summary", "type"],
            },
            output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            permissions=[Permission(resource="memory_candidate", operations=["create"])],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False,
            audit_required=True,
            idempotent=False,
        )

        def _store_candidate_fn(
            summary: str = "",
            type: str = "general",
            confidence: float = 0.5,
        ) -> ToolResult:
            if not summary or not summary.strip():
                return ToolResult(
                    status="error",
                    summary="summary is required",
                    error="Missing summary argument",
                )
            ws_id = self._current_workspace_id or "default"
            result = self.create_candidate_file(
                workspace_id=ws_id,
                text=summary.strip(),
                memory_type=type,
                confidence=max(0.0, min(1.0, confidence)),
                actor_id="assistant",
            )
            return ToolResult(
                status="ok",
                summary=f"Candidate memory stored (tag={type})",
                data=result,
            )

        # ── recall_memory ──

        recall_manifest = CapabilityManifest(
            name="recall_memory",
            version="1.0.0",
            type=CapabilityType.tool,
            description="Search past memories by semantic query. "
            "Use when you need details not covered in the current context, "
            "such as old preferences, past decisions, or specific facts.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing what you're looking for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {"results": {"type": "array"}},
            },
            permissions=[Permission(resource="memory_chunks", operations=["read"])],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False,
            audit_required=True,
            idempotent=True,
        )

        def _recall_memory_fn(
            query: str = "",
            limit: int = 5,
        ) -> ToolResult:
            if not query or not query.strip():
                return ToolResult(
                    status="error",
                    summary="query is required",
                    error="Missing query argument",
                )
            ws_id = self._current_workspace_id or "default"
            results = self.recall_search(query, ws_id, limit=max(1, min(50, limit)))
            if not results:
                return ToolResult(status="ok", summary="No matching memories found", data=[])
            lines = []
            for r in results:
                section = r.get("section", "general")
                text = r.get("text", "")
                score = r.get("score", 0.0)
                preview = text[:200].replace("\n", " ")
                lines.append(f"[{section}] (score={score:.2f}) {preview}")
            return ToolResult(
                status="ok",
                summary=f"Found {len(results)} memory match(es)",
                data={"results": results},
                details="\n".join(lines),
            )

        # ── memory.search (full retrieval pipeline: sparse + dense + RRF) ──

        search_manifest = CapabilityManifest(
            name="memory.search",
            version="1.0.0",
            type=CapabilityType.tool,
            description="Deep search stored memories using semantic + keyword retrieval. "
            "More thorough than recall_memory — searches the full memory store "
            "with hybrid sparse/dense + RRF fusion ranking. "
            "Use when you need to find something specific the user told you before, "
            "or when the current context is missing important background.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing what you're looking for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (1-20)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "properties": {"results": {"type": "array"}},
            },
            permissions=[Permission(resource="memory", operations=["read"])],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False,
            audit_required=True,
            idempotent=True,
        )

        def _search_memory_fn(
            query: str = "",
            limit: int = 5,
        ) -> ToolResult:
            if not query or not query.strip():
                return ToolResult(
                    status="error",
                    summary="query is required",
                    error="Missing query argument",
                )
            ws_id = self._current_workspace_id or "default"
            try:
                from cogito_agent.retrieval.query import MemoryQueryBuilder, MemoryQueryContext

                builder = MemoryQueryBuilder()
                ctx = builder.build(
                    current_message=query,
                    workspace_id=ws_id,
                    recent_user_messages=[],
                )
                result = self._retrieval_service.recall(ctx, limit=max(1, min(20, limit)))
                items = result.dynamic_memories + result.resident_memories
                if not items:
                    return ToolResult(
                        status="ok",
                        summary="No matching memories found",
                        data={"results": []},
                    )
                formatted = []
                for mem in items:
                    formatted.append({
                        "id": str(mem.get("id", "")),
                        "text": str(mem.get("text", ""))[:300],
                        "type": str(mem.get("type", "general")),
                        "confidence": float(mem.get("confidence", 0.0)),
                        "source": mem.get("retrieval_source", "dynamic"),
                    })
                return ToolResult(
                    status="ok",
                    summary=f"Found {len(formatted)} matching memories",
                    data={"results": formatted},
                )
            except Exception as exc:
                return ToolResult(
                    status="error",
                    summary=f"Memory search failed: {exc}",
                    error=str(exc),
                )

        if isinstance(cap_reg, CapabilityRegistry):
            cap_reg.register("memory.store_candidate", cand_manifest, _store_candidate_fn)
            cap_reg.register("recall_memory", recall_manifest, _recall_memory_fn)
            cap_reg.register("memory.search", search_manifest, _search_memory_fn)

    # ── private helpers ──

    def _try_index(self, memory_id: str, text: str) -> None:
        if self._embedding_index is None:
            return
        try:
            self._embedding_index.index_memory(memory_id, text)
        except Exception as e:
            logger.warning("Embedding index failed for %s: %s", memory_id, e)

    def _mark_stale(self, memory_id: str) -> None:
        if self._embedding_index is None:
            return
        try:
            self._embedding_index.mark_stale(memory_id)
        except Exception:
            pass

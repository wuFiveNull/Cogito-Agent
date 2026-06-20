from __future__ import annotations

import logging
import uuid
from typing import Any

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryCandidateRepository,
    MemoryEditRepository,
    MemoryRepository,
)

from ..embedding.service import MemoryEmbeddingIndexService
from ..governance import AuditLogger

logger = logging.getLogger(__name__)


class MemoryApplicationService:
    """Unified entry point for all memory mutations.

    Every write operation maintains the embedding lifecycle:
    - Create    → save memory, attempt embed (best-effort)
    - Edit      → save version, stale old embedding, attempt new embed
    - Merge     → update target, archive source, stale/reindex both
    - Archive   → mark archived (embeddings stay, Dense ignores archived)
    - Restore   → check embedding, reindex if missing for current model
    - Delete    → soft delete, remove embeddings from retrieval
    """

    def __init__(
        self,
        db: Database,
        embedding_index: MemoryEmbeddingIndexService | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._db = db
        self._mem_repo = MemoryRepository(db)
        self._edit_repo = MemoryEditRepository(db)
        self._cand_repo = MemoryCandidateRepository(db)
        self._embedding_index = embedding_index
        self._audit = audit or AuditLogger(db)

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
        self._audit.log(
            actor_id=actor_id, action="memory.create",
            resource=f"memory:{mid}", workspace_id=workspace_id,
            decision="allow", reason=f"type={memory_type}",
        )
        return memory

    def edit_memory(
        self, mid: str, workspace_id: str, new_text: str,
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
        return ok

    def correct_memory(
        self, mid: str, workspace_id: str, new_text: str,
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
        self, source_mid: str, target_mid: str, workspace_id: str,
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
        self, mid: str, workspace_id: str, actor_id: str = "cli",
    ) -> bool:
        ok = self._mem_repo.archive(mid, workspace_id)
        return ok

    def restore_memory(
        self, mid: str, workspace_id: str, actor_id: str = "cli",
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
        self, mid: str, workspace_id: str, actor_id: str = "cli",
    ) -> bool:
        ok = self._edit_repo.hard_delete(mid, workspace_id)
        if ok and self._embedding_index:
            self._embedding_index.delete_or_deactivate(mid)
        return ok

    def accept_candidate(
        self, candidate_id: str, actor_id: str = "cli",
    ) -> dict[str, object] | None:
        result = self._cand_repo.accept(candidate_id)
        if result:
            self._audit.log(
                actor_id=actor_id, action="memory.accept_candidate",
                resource=f"candidate:{candidate_id}",
                workspace_id=str(result.get("workspace_id", "")),
                decision="allow",
            )
            # Best-effort embedding indexing for the new memory
            created_mid = str(result.get("memory_id", ""))
            if not created_mid:
                cand_text = str(result.get("text", ""))
                if cand_text and self._embedding_index is not None:
                    mems = self._db.connection.execute(
                        "SELECT id FROM memories WHERE text = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",
                        (cand_text,),
                    ).fetchall()
                    for row in mems:
                        self._try_index(str(row["id"]), cand_text)
        return result

    def reject_candidate(
        self, candidate_id: str, actor_id: str = "cli",
    ) -> dict[str, object] | None:
        result = self._cand_repo.reject(candidate_id)
        if result:
            self._audit.log(
                actor_id=actor_id, action="memory.reject_candidate",
                resource=f"candidate:{candidate_id}",
                workspace_id=str(result.get("workspace_id", "")),
                decision="deny",
            )
        return result

    def consolidate_memories(self, workspace_id: str, actor_id: str = "cli") -> int:
        from cogito_agent.runtime.drift import DriftMaintenance
        dm = DriftMaintenance(self._db)
        count = dm.consolidate_memories(workspace_id)
        if count:
            self._audit.log(
                actor_id=actor_id, action="memory.consolidate",
                resource="memory", workspace_id=workspace_id,
                decision="allow", reason=f"removed {count} duplicates",
            )
        return count

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

from __future__ import annotations

from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryCandidateRepository,
    MemoryEditRepository,
    MemoryRepository,
)


def _run_memory_list(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    repo = MemoryRepository(db)
    memories = repo.list_by_workspace(ns.workspace_id)
    if not memories:
        print("  No memories found.")
    else:
        print(f"  Memories ({len(memories)}):")
        for m in memories:
            mid = str(m.get("id", ""))[:8]
            text = str(m.get("text", ""))[:60]
            mtype = str(m.get("type", "general"))
            pinned = " [PINNED]" if m.get("pinned_at") else ""
            print(f"    [{mtype}]{pinned} {mid}  {text}")
    db.close()


def _run_memory_search(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    retriever = MemoryRetriever(db)
    results = retriever.search(ns.workspace_id, ns.query, limit=20)
    if not results:
        print("  No results found.")
    else:
        print(f"  Results ({len(results)}):")
        for m in results:
            mid = str(m.get("id", ""))[:8]
            text = str(m.get("text", ""))[:80]
            score = m.get("confidence", 0.5)
            mtype = str(m.get("type", "general"))
            print(f"    [{mtype}] {mid}  (conf={score})  {text}")
    db.close()


def _run_memory_review(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    repo = MemoryCandidateRepository(db)
    candidates = repo.list_pending(ns.workspace_id)
    if not candidates:
        print("  No pending candidates.")
    else:
        print(f"  Pending candidates ({len(candidates)}):")
        for c in candidates:
            cid = str(c.get("id", ""))[:8]
            text = str(c.get("text", ""))[:60]
            mtype = str(c.get("type", "general"))
            print(f"    [{mtype}] {cid}  {text}")
    db.close()


def _run_memory_accept(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    audit = AuditLogger(db)
    repo = MemoryCandidateRepository(db)
    result = repo.accept(ns.candidate_id)
    if result:
        print(f"  Accepted: {str(result.get('text', ''))[:60]}")
        audit.log(
            actor_id="cli", action="memory.accept",
            resource=f"candidate:{ns.candidate_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user approved",
        )
    else:
        print("  Candidate not found or already resolved.")
    db.close()


def _run_memory_reject(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    audit = AuditLogger(db)
    repo = MemoryCandidateRepository(db)
    result = repo.reject(ns.candidate_id)
    if result:
        print(f"  Rejected: {str(result.get('text', ''))[:60]}")
        audit.log(
            actor_id="cli", action="memory.reject",
            resource=f"candidate:{ns.candidate_id}",
            workspace_id=ns.workspace_id,
            decision="deny", reason="user rejected",
        )
    else:
        print("  Candidate not found or already resolved.")
    db.close()


def _run_memory_delete(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    audit = AuditLogger(db)
    repo = MemoryEditRepository(db)
    if repo.hard_delete(ns.memory_id, ns.workspace_id):
        print(f"  Deleted memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.delete",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user deleted",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_pin(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    from datetime import UTC, datetime
    db.connection.execute(
        "UPDATE memories SET pinned_at = ?"
        " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
        (datetime.now(UTC).isoformat(), ns.memory_id, ns.workspace_id),
    )
    if db.connection.total_changes:
        db.connection.commit()
        print(f"  Pinned memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.pin",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user pinned",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_consolidate(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    audit = AuditLogger(db)
    from cogito_agent.runtime.drift import DriftMaintenance
    dm = DriftMaintenance(db)
    count = dm.consolidate_memories(ns.workspace_id)
    print(f"  Consolidated: {count} duplicate(s) removed")
    if count:
        audit.log(
            actor_id="cli", action="memory.consolidate",
            resource="memory",
            workspace_id=ns.workspace_id,
            decision="allow", reason=f"removed {count} duplicates",
        )
    db.close()

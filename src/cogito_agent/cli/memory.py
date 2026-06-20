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
    db.migrate()

    if getattr(ns, "explain", False):
        from cogito_agent.config import Settings
        from cogito_agent.retrieval.service import create_retrieval_service

        cfg = Settings.get()
        svc = create_retrieval_service(db, config=cfg.memory)
        explain = svc.explain_search(ns.workspace_id, ns.query, limit=20)
        print(f"  Trace ID:         {explain.get('trace_id', '')}")
        print(f"  Health state:     {explain.get('health_state', '')}")
        print(f"  Retrieval mode:   {explain['mode']}")
        print(f"  Gate mode:        {explain.get('gate_mode', '')}")
        if explain.get("degraded_reason"):
            print(f"  Degraded reason:  {explain['degraded_reason']}")
        print(f"  Sparse candidates: {explain['sparse_candidate_count']}")
        print(f"  Dense candidates:  {explain['dense_candidate_count']}")
        print(f"  Union candidates:  {explain['union_candidate_count']}")
        print(f"  Selected:          {explain['selected_count']}")
        print(f"  Resident:          {explain['resident_count']}")
        if explain.get("embedding_provider"):
            emb = explain
            print(
                f"  Embedding:         {emb['embedding_provider']}/"
                f"{emb['embedding_model']} dim={emb['embedding_dimension']}"
            )
        if explain.get("score_breakdowns"):
            print("  Score breakdowns:")
            for mid, breakdown in explain["score_breakdowns"].items():
                print(
                    f"    {mid}: dense={breakdown['dense_score']:.4f} "
                    f"sparse={breakdown['sparse_score']:.4f} "
                    f"recency={breakdown['recency_score']:.4f} "
                    f"final={breakdown['final_score']:.4f}"
                )
        if explain.get("selected"):
            print("  Selected memories:")
            for m in explain["selected"]:
                print(f"    [{m['type']}] ({m['source']}) {m['id'][:8]}  {m['text']}")
        db.close()
        return

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


def _run_memory_edit(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.edit_text(ns.memory_id, ns.workspace_id, ns.text)
    if success:
        print(f"  Edited memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.edit",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user edited",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_correct(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.correct_text(ns.memory_id, ns.workspace_id, ns.text)
    if success:
        print(f"  Corrected memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.correct",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user corrected",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_archive(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.archive(ns.memory_id, ns.workspace_id)
    if success:
        print(f"  Archived memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.archive",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user archived",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_unarchive(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.unarchive(ns.memory_id, ns.workspace_id)
    if success:
        print(f"  Unarchived memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.unarchive",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user unarchived",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_unpin(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.unpin(ns.memory_id, ns.workspace_id)
    if success:
        print(f"  Unpinned memory: {ns.memory_id}")
        audit.log(
            actor_id="cli", action="memory.unpin",
            resource=f"memory:{ns.memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user unpinned",
        )
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_merge(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    audit = AuditLogger(db)
    repo = MemoryRepository(db)
    success = repo.merge(ns.source_memory_id, ns.target_memory_id, ns.workspace_id)
    if success:
        print(f"  Merged {ns.source_memory_id} into {ns.target_memory_id}")
        audit.log(
            actor_id="cli", action="memory.merge",
            resource=f"memory:merge:{ns.source_memory_id}->{ns.target_memory_id}",
            workspace_id=ns.workspace_id,
            decision="allow", reason="user merged",
        )
    else:
        print("  One or both memories not found.")
    db.close()


def _get_provider(cfg):
    from cogito_agent.embedding.service import create_embedding_provider_from_config
    return create_embedding_provider_from_config(cfg.memory.embedding)


def _run_embeddings_status(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService

    cfg = Settings.get()
    provider = _get_provider(cfg)
    if provider is None:
        print("  Embedding provider: disabled")
        db.close()
        return

    svc = MemoryEmbeddingIndexService(db, provider)
    ws = ns.workspace_id or "default"
    s = svc.status(ws)
    print(f"  Provider:       {s['provider']}")
    print(f"  Model:          {s['model']}")
    print(f"  Dimension:      {s['dimension']}")
    print(f"  Is semantic:    {s['is_semantic']}")
    print(f"  Version:        {s['embedding_version']}")
    print(f"  Ready:          {s['ready']}")
    print(f"  Pending:        {s['pending']}")
    print(f"  Failed:         {s['failed']}")
    print(f"  Stale:          {s['stale']}")
    print(f"  Total memories: {s['total_memories']}")
    print(f"  Coverage:       {s['coverage_pct']}%")
    db.close()


def _run_embeddings_doctor(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.config import Settings

    cfg = Settings.get()
    es = cfg.memory.embedding
    print(f"  Config provider: {es.provider}")
    print(f"  Config model:    {es.model}")
    print(f"  Config base_url: {es.base_url or '(none)'}")
    if es.api_key_secret_name:
        print(f"  Secret name:     {es.api_key_secret_name}")
    if es.api_key_env:
        import os
        av = bool(os.environ.get(es.api_key_env))
        st = "available" if av else "unavailable"
        print(f"  API key env:     {es.api_key_env} -> {st}")

    try:
        provider = _get_provider(cfg)
    except Exception as e:
        print(f"  Provider init:   FAILED - {e}")
        db.close()
        return

    if provider is None:
        print("  Provider:        disabled (sparse-only)")
        db.close()
        return

    health = provider.health_check()
    print("  Provider init:   OK")
    print(f"  Health:          {'healthy' if health.healthy else 'UNHEALTHY'}")
    print(f"  Provider name:   {health.provider_name}")
    print(f"  Model:           {health.model_name}")
    print(f"  Dimension:       {health.dimension}")
    print(f"  Is semantic:     {health.is_semantic}")
    if not health.healthy:
        print(f"  Error:           {health.error_message}")
    db.close()


def _run_embeddings_rebuild(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService

    cfg = Settings.get()
    provider = _get_provider(cfg)
    if provider is None:
        print("  Embedding provider not available.")
        db.close()
        return

    svc = MemoryEmbeddingIndexService(db, provider)
    ws = ns.workspace_id or "default"
    batch = ns.batch_size or 32
    force = getattr(ns, "force", False)
    result = svc.rebuild_workspace(ws, force=force, batch_size=batch)
    print(f"  Workspace:    {result['workspace_id']}")
    print(f"  Total:        {result['total']}")
    print(f"  Indexed:      {result['indexed']}")
    print(f"  Failed:       {result['failed']}")
    print(f"  Skipped:      {result['skipped']}")
    if result["failed"] > 0:
        print("  WARNING: Some embeddings failed!")
    db.close()


def _run_embeddings_retry_failed(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService

    cfg = Settings.get()
    provider = _get_provider(cfg)
    if provider is None:
        print("  Embedding provider not available.")
        db.close()
        return

    svc = MemoryEmbeddingIndexService(db, provider)
    ws = ns.workspace_id or "default"
    result = svc.retry_failed(ws)
    print(f"  Retried: {result['succeeded']} succeeded, {result['failed']} failed")
    db.close()


def _run_embeddings_purge_stale(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService

    cfg = Settings.get()
    provider = _get_provider(cfg)
    if provider is None:
        print("  Embedding provider not available.")
        db.close()
        return

    svc = MemoryEmbeddingIndexService(db, provider)
    ws = ns.workspace_id or "default"
    count = svc.purge_stale(ws)
    print(f"  Purged {count} stale embedding(s)")
    db.close()

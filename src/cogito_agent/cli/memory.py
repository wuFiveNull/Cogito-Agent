from __future__ import annotations

from typing import Any

from cogito_agent.retrieval.service import create_retrieval_service
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MemoryRepository


def _get_app_svc(db: Database | None = None) -> Any:
    """Return ApplicationServices via bootstrap factory."""
    from cogito_agent.bootstrap import build_application_services
    from cogito_agent.config import Settings
    from cogito_agent.storage import Database as _Db

    if db is None:
        db = _Db()
        db.initialize()
        db.migrate()
    cfg = Settings.get()
    return build_application_services(db, config=cfg.memory)


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

    svc = create_retrieval_service(db)
    results = svc.search_compat(ns.workspace_id, ns.query, limit=20)
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
    from cogito_agent.storage import Database, MemoryItemRepository

    db = Database()
    db.initialize()
    try:
        repo = MemoryItemRepository(db)
        rows = repo.list_active_with_filters(ns.workspace_id, limit=50)
        if not rows:
            print("  No memories found.")
        else:
            print(f"  Memories ({len(rows)}):")
            for r in rows:
                text = str(r["summary"])[:60]
                mtype = str(r["memory_type"])
                cid = str(r["id"])[:8]
                reinf = int(r["reinforcement"])
                print(f"    [{mtype}] {cid}  (x{reinf}) {text}")
    except Exception as e:
        print(f"  Error: {e}")





def _run_memory_delete(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    if svc.memory_application.delete_memory(ns.memory_id, ns.workspace_id, actor_id="cli"):
        print(f"  Deleted memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_pin(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.storage.repositories import MemoryRepository

    repo = MemoryRepository(db)
    if repo.pin(ns.memory_id, ns.workspace_id):
        print(f"  Pinned memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_consolidate(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    count = svc.memory_application.consolidate_memories(ns.workspace_id, actor_id="cli")
    print(f"  Consolidated: {count} duplicate(s) removed")
    db.close()


def _run_memory_edit(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    success = svc.memory_application.edit_memory(
        ns.memory_id, ns.workspace_id, ns.text, actor_id="cli"
    )
    if success:
        print(f"  Edited memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_correct(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    success = svc.memory_application.correct_memory(
        ns.memory_id, ns.workspace_id, ns.text, actor_id="cli"
    )
    if success:
        print(f"  Corrected memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_archive(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    success = svc.memory_application.archive_memory(ns.memory_id, ns.workspace_id, actor_id="cli")
    if success:
        print(f"  Archived memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_unarchive(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    success = svc.memory_application.restore_memory(ns.memory_id, ns.workspace_id, actor_id="cli")
    if success:
        print(f"  Unarchived memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_unpin(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    from cogito_agent.storage.repositories import MemoryRepository

    repo = MemoryRepository(db)
    success = repo.unpin(ns.memory_id, ns.workspace_id)
    if success:
        print(f"  Unpinned memory: {ns.memory_id}")
    else:
        print("  Memory not found.")
    db.close()


def _run_memory_merge(args: Any) -> None:
    ns = args
    db = Database(ns.db_path)
    db.initialize()
    db.migrate()
    svc = _get_app_svc(db)
    success = svc.memory_application.merge_memories(
        ns.source_memory_id, ns.target_memory_id, ns.workspace_id, actor_id="cli"
    )
    if success:
        print(f"  Merged {ns.source_memory_id} into {ns.target_memory_id}")
    else:
        print("  One or both memories not found.")
    db.close()


def _get_provider(cfg: Any) -> Any:
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



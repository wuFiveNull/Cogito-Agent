"""MemoryReader — memory_items / memories 只读查询，不依赖 RuntimeKernel。"""

from __future__ import annotations

from typing import Any

from cogito_agent.storage import Database


class MemoryReader:
    """记忆条目的只读查询（Memory v2 memory_items + 兼容旧版 memories）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Memory Items (v2) ──────────────────────────────────────────────────

    def list_memory_items(
        self,
        workspace_id: str = "default",
        *,
        memory_type: str = "",
        status: str = "active",
        exclude_type: str = "_recent_context",
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "updated_at",
        sort_order: str = "DESC",
    ) -> list[dict[str, object]]:
        safe_sort = sort_by if sort_by in ("updated_at", "created_at", "reinforcement", "emotional_weight") else "updated_at"
        safe_order = "ASC" if sort_order.upper() == "ASC" else "DESC"
        where_clauses = ["workspace_id = ?"]
        params: list[object] = [workspace_id]
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if memory_type:
            where_clauses.append("memory_type = ?")
            params.append(memory_type)
        if exclude_type:
            where_clauses.append("memory_type != ?")
            params.append(exclude_type)
        where = " AND ".join(where_clauses)
        cur = self._db.connection.execute(
            f"SELECT id, workspace_id, memory_type, summary, reinforcement,"
            f" emotional_weight, source_ref, status, created_at, updated_at"
            f" FROM memory_items"
            f" WHERE {where}"
            f" ORDER BY {safe_sort} {safe_order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_memory_item(self, item_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, memory_type, summary, reinforcement,"
            " emotional_weight, source_ref, status, extra_json, created_at, updated_at"
            " FROM memory_items WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def count_memory_items(
        self,
        workspace_id: str = "default",
        *,
        status: str = "active",
        memory_type: str = "",
        exclude_type: str = "_recent_context",
    ) -> int:
        where_clauses = ["workspace_id = ?"]
        params: list[object] = [workspace_id]
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        if memory_type:
            where_clauses.append("memory_type = ?")
            params.append(memory_type)
        if exclude_type:
            where_clauses.append("memory_type != ?")
            params.append(exclude_type)
        where = " AND ".join(where_clauses)
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM memory_items WHERE {where}", params
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Legacy Memories ────────────────────────────────────────────────────

    def list_legacy_memories(
        self,
        workspace_id: str = "default",
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, text, memory_type, confidence,"
            " source_ref, is_archived, created_at, updated_at"
            " FROM memories"
            " WHERE workspace_id = ? AND deleted_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def memory_stats(self, workspace_id: str = "default") -> dict[str, int]:
        """汇总统计数据，兼容现有 Console 的 _mem_stats()。"""
        v2_row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM memory_items"
            " WHERE workspace_id = ? AND status = 'active'"
            " AND memory_type != '_recent_context'",
            (workspace_id,),
        ).fetchone()
        v2_count = v2_row["cnt"] if v2_row else 0

        old_row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM memories"
            " WHERE workspace_id = ? AND deleted_at IS NULL"
            " AND (is_archived = 0 OR is_archived IS NULL)",
            (workspace_id,),
        ).fetchone()
        old_active = old_row["cnt"] if old_row else 0

        arch_row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM memories"
            " WHERE workspace_id = ? AND deleted_at IS NULL"
            " AND is_archived = 1",
            (workspace_id,),
        ).fetchone()
        archived = arch_row["cnt"] if arch_row else 0

        return {
            "total": v2_count + old_active + archived,
            "pending": 0,
            "accepted": v2_count + old_active,
            "archived": archived,
            "stale": 0,
        }

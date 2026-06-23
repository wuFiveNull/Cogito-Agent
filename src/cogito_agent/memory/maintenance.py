from __future__ import annotations

from typing import Any


class MemoryMaintenance:
    """Background maintenance tasks for the legacy ``memories`` table.

    These operations were moved out of ``runtime.drift.DriftMaintenance``
    to eliminate the cross-layer import ``memory → runtime``.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    def consolidate_legacy_memories(self, workspace_id: str | None = None) -> int:
        """Deduplicate the legacy ``memories`` table by text content.

        Returns the number of duplicate rows removed.
        """
        if workspace_id:
            rows = self._db.connection.execute(
                "SELECT id, text, workspace_id, rowid FROM memories"
                " WHERE deleted_at IS NULL AND workspace_id = ?"
                " ORDER BY text, created_at ASC",
                (workspace_id,),
            ).fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT id, text, workspace_id, rowid FROM memories"
                " WHERE deleted_at IS NULL"
                " ORDER BY text, created_at ASC"
            ).fetchall()
        removed = 0
        seen: dict[str, list[dict[str, object]]] = {}
        for r in rows:
            text = str(r["text"])
            if text not in seen:
                seen[text] = [dict(r)]
            else:
                seen[text].append(dict(r))
        for text, group in seen.items():
            if len(group) <= 1:
                continue
            for dup in group[1:]:
                mid = dup["id"]
                wid = str(dup["workspace_id"])
                rowid = dup["rowid"]
                self._db.connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
                self._db.connection.execute(
                    "DELETE FROM memories WHERE id = ? AND workspace_id = ?",
                    (mid, wid),
                )
                removed += 1
        if removed:
            self._db.connection.commit()
        return removed

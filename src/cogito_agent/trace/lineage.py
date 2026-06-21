from __future__ import annotations

import uuid

from cogito_agent.storage import Database


class SourceLineage:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        trace_id: str,
        output_ref: str,
        source_type: str,
        source_id: str,
        span_id: str = "",
        note: str = "",
    ) -> dict[str, object]:
        lid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO source_lineage"
            " (id, trace_id, output_ref, source_type, source_id, span_id, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lid, trace_id, output_ref, source_type, source_id, span_id, note),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT * FROM source_lineage WHERE id = ?", (lid,))
        return dict(cur.fetchone())

    def list_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM source_lineage WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

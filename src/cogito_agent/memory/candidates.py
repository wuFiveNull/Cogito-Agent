from __future__ import annotations

import uuid

from cogito_agent.storage import Database


class CandidateExtractor:
    def __init__(self, db: Database) -> None:
        self._db = db

    def extract(
        self,
        workspace_id: str,
        session_id: str,
        source_message_id: str,
        text: str,
        type: str = "general",
        reason: str = "",
        confidence: float = 0.5,
    ) -> dict[str, object]:
        cid = str(uuid.uuid4())
        cur = self._db.connection.execute(
            "INSERT INTO memory_candidates"
            " (id, workspace_id, session_id, text, type, reason, confidence, source_message_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, workspace_id, session_id, text, type, reason, confidence, source_message_id),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        row = cur.fetchone()
        return dict(row) if row else {"id": cid}

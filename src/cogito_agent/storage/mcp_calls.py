from __future__ import annotations

from .database import Database


class SqliteMCPCallReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list_recent(
        self,
        server_name: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        escaped = server_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"mcp\\_{escaped}\\_%"
        rows = self._db.connection.execute(
            "SELECT trace_id, capability_name, decision, status, output_summary,"
            " error, latency_ms FROM tool_calls"
            " WHERE capability_name LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?",
            (pattern, max(1, min(limit, 100))),
        ).fetchall()
        return [dict(row) for row in rows]

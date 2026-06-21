from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from cogito_agent.storage import Database

from .server import MCPServerConfig


def tool_schema_hash(tool: dict[str, object]) -> str:
    schema = tool.get("inputSchema", {})
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class MCPTrustStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def stage_server(self, config: MCPServerConfig) -> str:
        now = datetime.now(UTC).isoformat()
        config_hash = config.fingerprint()
        existing = self.get_server(config.name)
        status = "pending"
        if existing and existing.get("config_hash") == config_hash:
            status = str(existing.get("trust_status", "pending"))
        persisted_config = config.model_dump(mode="json")
        persisted_config["env"] = {key: "[REDACTED]" for key in config.env}
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO mcp_servers"
                " (name, config_hash, config_json, trust_status, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET config_hash=excluded.config_hash,"
                " config_json=excluded.config_json, trust_status=excluded.trust_status,"
                " enabled=excluded.enabled, updated_at=excluded.updated_at",
                (
                    config.name,
                    config_hash,
                    json.dumps(persisted_config, sort_keys=True),
                    status,
                    int(config.enabled),
                    now,
                    now,
                ),
            )
            if status == "pending":
                self._db.connection.execute(
                    "UPDATE mcp_tool_grants SET revoked_at=? WHERE server_name=?",
                    (now, config.name),
                )
        return status

    def trust_server(self, name: str) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE mcp_servers SET trust_status='trusted', updated_at=? WHERE name=?",
                (datetime.now(UTC).isoformat(), name),
            )
        return cursor.rowcount == 1

    def block_server(self, name: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE mcp_servers SET trust_status='blocked', updated_at=? WHERE name=?",
                (now, name),
            )
            self._db.connection.execute(
                "UPDATE mcp_tool_grants SET revoked_at=? WHERE server_name=?",
                (now, name),
            )
        return cursor.rowcount == 1

    def get_server(self, name: str) -> dict[str, object] | None:
        row = self._db.connection.execute(
            "SELECT * FROM mcp_servers WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_server_config(self, name: str) -> MCPServerConfig | None:
        record = self.get_server(name)
        if not record:
            return None
        raw = json.loads(str(record["config_json"]))
        if isinstance(raw.get("env"), dict):
            raw["env"] = {key: value for key, value in raw["env"].items() if value != "[REDACTED]"}
        return MCPServerConfig.model_validate(raw)

    def list_servers(self) -> list[dict[str, object]]:
        rows = self._db.connection.execute("SELECT * FROM mcp_servers ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def stage_tool(self, server_name: str, tool: dict[str, object]) -> bool:
        name = str(tool.get("name", "unknown"))
        schema_hash = tool_schema_hash(tool)
        existing = self.get_tool_grant(server_name, name, include_revoked=True)
        changed = existing is None or existing.get("schema_hash") != schema_hash
        if changed:
            with self._db.connection:
                self._db.connection.execute(
                    "INSERT INTO mcp_tool_grants"
                    " (server_name, tool_name, schema_hash, risk_level,"
                    " allowed_sources_json, requires_approval, granted_at, revoked_at)"
                    " VALUES (?, ?, ?, 'high', '[\"interactive\"]', 1, NULL, NULL)"
                    " ON CONFLICT(server_name, tool_name) DO UPDATE SET"
                    " schema_hash=excluded.schema_hash, risk_level='high',"
                    " allowed_sources_json='[\"interactive\"]', requires_approval=1,"
                    " granted_at=NULL, revoked_at=NULL",
                    (server_name, name, schema_hash),
                )
        return changed

    def grant_tool(
        self,
        server_name: str,
        tool_name: str,
        *,
        schema_hash: str,
        allowed_sources: list[str] | None = None,
        requires_approval: bool = True,
    ) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE mcp_tool_grants SET allowed_sources_json=?, requires_approval=?,"
                " granted_at=?, revoked_at=NULL"
                " WHERE server_name=? AND tool_name=? AND schema_hash=?",
                (
                    json.dumps(allowed_sources or ["interactive"]),
                    int(requires_approval),
                    datetime.now(UTC).isoformat(),
                    server_name,
                    tool_name,
                    schema_hash,
                ),
            )
        return cursor.rowcount == 1

    def revoke_tool(self, server_name: str, tool_name: str) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE mcp_tool_grants SET revoked_at=?"
                " WHERE server_name=? AND tool_name=? AND revoked_at IS NULL",
                (datetime.now(UTC).isoformat(), server_name, tool_name),
            )
        return cursor.rowcount == 1

    def get_tool_grant(
        self,
        server_name: str,
        tool_name: str,
        *,
        include_revoked: bool = False,
    ) -> dict[str, object] | None:
        sql = "SELECT * FROM mcp_tool_grants WHERE server_name=? AND tool_name=?"
        if not include_revoked:
            sql += " AND granted_at IS NOT NULL AND revoked_at IS NULL"
        row = self._db.connection.execute(sql, (server_name, tool_name)).fetchone()
        return dict(row) if row else None

    def list_tool_grants(self, server_name: str) -> list[dict[str, object]]:
        rows = self._db.connection.execute(
            "SELECT * FROM mcp_tool_grants WHERE server_name=? ORDER BY tool_name",
            (server_name,),
        ).fetchall()
        return [dict(row) for row in rows]

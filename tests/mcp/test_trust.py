from __future__ import annotations

from cogito_agent.mcp import MCPServerConfig, MCPTrustStore
from cogito_agent.mcp.trust import tool_schema_hash
from cogito_agent.storage import Database


def _store() -> tuple[Database, MCPTrustStore]:
    db = Database()
    db.initialize()
    db.migrate()
    return db, MCPTrustStore(db)


def test_new_and_changed_server_requires_trust() -> None:
    db, store = _store()
    try:
        config = MCPServerConfig(name="local", command="server")
        assert store.stage_server(config) == "pending"
        assert store.trust_server("local") is True
        assert store.stage_server(config) == "trusted"

        changed = MCPServerConfig(name="local", command="different-server")
        assert store.stage_server(changed) == "pending"
        assert store.get_server("local")["trust_status"] == "pending"  # type: ignore[index]
    finally:
        db.close()


def test_tool_schema_change_revokes_grant() -> None:
    db, store = _store()
    try:
        config = MCPServerConfig(name="local", command="server")
        store.stage_server(config)
        store.trust_server("local")
        tool = {"name": "read", "inputSchema": {"type": "object"}}
        assert store.stage_tool("local", tool) is True
        assert store.get_tool_grant("local", "read") is None
        assert (
            store.grant_tool(
                "local",
                "read",
                schema_hash=tool_schema_hash(tool),
            )
            is True
        )
        assert store.get_tool_grant("local", "read") is not None

        changed = {
            "name": "read",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        }
        assert store.stage_tool("local", changed) is True
        assert store.get_tool_grant("local", "read") is None
    finally:
        db.close()


def test_grant_rejects_stale_schema_hash() -> None:
    db, store = _store()
    try:
        store.stage_server(MCPServerConfig(name="local", command="server"))
        tool = {"name": "read", "inputSchema": {"type": "object"}}
        store.stage_tool("local", tool)
        assert store.grant_tool("local", "read", schema_hash="stale") is False
    finally:
        db.close()


def test_persisted_server_config_does_not_store_env_secrets() -> None:
    db, store = _store()
    try:
        config = MCPServerConfig(
            name="local",
            command="server",
            env={"API_TOKEN": "super-secret-value"},
        )
        store.stage_server(config)
        record = store.get_server("local")
        assert record is not None
        assert "super-secret-value" not in str(record["config_json"])
        restored = store.get_server_config("local")
        assert restored is not None
        assert restored.env == {}
    finally:
        db.close()


def test_tool_grant_can_be_revoked() -> None:
    db, store = _store()
    try:
        store.stage_server(MCPServerConfig(name="local", command="server"))
        tool = {"name": "read", "inputSchema": {"type": "object"}}
        store.stage_tool("local", tool)
        assert store.grant_tool(
            "local",
            "read",
            schema_hash=tool_schema_hash(tool),
        )
        assert store.revoke_tool("local", "read")
        assert store.get_tool_grant("local", "read") is None
    finally:
        db.close()

CREATE TABLE IF NOT EXISTS mcp_servers (
    name TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    trust_status TEXT NOT NULL DEFAULT 'pending',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_tool_grants (
    server_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'high',
    allowed_sources_json TEXT NOT NULL DEFAULT '["interactive"]',
    requires_approval INTEGER NOT NULL DEFAULT 1,
    granted_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (server_name, tool_name),
    FOREIGN KEY (server_name) REFERENCES mcp_servers(name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_trust ON mcp_servers(trust_status);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_grants_server ON mcp_tool_grants(server_name);

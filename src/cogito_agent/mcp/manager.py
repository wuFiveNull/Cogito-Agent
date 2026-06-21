from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.shared import CapabilityManifest, CapabilityType, RiskLevel

from .client import MCPClient
from .server import MCPServerConfig
from .trust import MCPTrustStore, tool_schema_hash


class MCPServerManager:
    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        trust_store: MCPTrustStore | None = None,
    ) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._pending_configs: dict[str, MCPServerConfig] = {}
        self._registered_tools: dict[str, set[str]] = {}
        self._cap_reg = capability_registry
        self._trust = trust_store
        self._config_dir: str | None = None

    def add_server(self, config: MCPServerConfig) -> None:
        if self._trust is not None:
            status = self._trust.stage_server(config)
            self._pending_configs[config.name] = config
            if status != "trusted":
                return
        self._connect_server(config)

    def _connect_server(self, config: MCPServerConfig) -> None:
        client = MCPClient(config)
        client.connect()
        self._clients[config.name] = client
        for tool in client.tools:
            if self._trust is not None:
                self._trust.stage_tool(config.name, tool)
                grant = self._trust.get_tool_grant(config.name, str(tool.get("name", "unknown")))
                if grant is None or grant.get("schema_hash") != tool_schema_hash(tool):
                    continue
            self._register_tool(config, tool)

    def _register_tool(self, config: MCPServerConfig, tool: dict[str, Any]) -> None:
        tool_name = str(tool.get("name", "unknown"))
        grant = (
            self._trust.get_tool_grant(config.name, tool_name) if self._trust is not None else None
        )
        allowed_contexts = ["interactive"]
        requires_approval = True
        if grant is not None:
            raw_contexts = json.loads(str(grant["allowed_sources_json"]))
            if isinstance(raw_contexts, list):
                allowed_contexts = [str(value) for value in raw_contexts]
            requires_approval = bool(grant["requires_approval"])
        mcp_tool_name = f"mcp_{config.name}_{tool_name}"
        manifest = CapabilityManifest(
            name=mcp_tool_name,
            version="1.0.0",
            type=CapabilityType.mcp_server,
            description=str(tool.get("description", "")),
            input_schema=tool.get("inputSchema", {}),
            output_schema={},
            permissions=[],
            risk_level=RiskLevel.high,
            allowed_contexts=allowed_contexts,
            approval_required=requires_approval,
            audit_required=True,
            idempotent=False,
        )
        self._cap_reg.register(
            mcp_tool_name,
            manifest,
            self._make_mcp_invoker(config.name, tool_name),
        )
        self._registered_tools.setdefault(config.name, set()).add(mcp_tool_name)

    def trust_server(self, name: str) -> bool:
        if self._trust is None or not self._trust.trust_server(name):
            return False
        config = self._pending_configs.get(name) or self._trust.get_server_config(name)
        if config is None:
            return False
        self._connect_server(config)
        return True

    def grant_tool(
        self,
        server_name: str,
        tool_name: str,
        *,
        schema_hash: str,
        allowed_sources: list[str] | None = None,
        requires_approval: bool = True,
    ) -> bool:
        if self._trust is None:
            return False
        granted = self._trust.grant_tool(
            server_name,
            tool_name,
            schema_hash=schema_hash,
            allowed_sources=allowed_sources,
            requires_approval=requires_approval,
        )
        if not granted:
            return False
        client = self._clients.get(server_name)
        config = self._pending_configs.get(server_name) or self._trust.get_server_config(
            server_name
        )
        if client is not None and config is not None:
            tool = next(
                (item for item in client.tools if str(item.get("name")) == tool_name),
                None,
            )
            if tool is not None:
                self._register_tool(config, tool)
        return True

    def revoke_tool(self, server_name: str, tool_name: str) -> bool:
        if self._trust is None or not self._trust.revoke_tool(server_name, tool_name):
            return False
        capability_name = f"mcp_{server_name}_{tool_name}"
        self._cap_reg.unregister(capability_name)
        self._registered_tools.setdefault(server_name, set()).discard(capability_name)
        return True

    def block_server(self, name: str) -> bool:
        if self._trust is None or not self._trust.block_server(name):
            return False
        self.remove_server(name)
        return True

    def remove_server(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client:
            client.disconnect()
        for capability_name in self._registered_tools.pop(name, set()):
            self._cap_reg.unregister(capability_name)

    def set_config_dir(self, directory: str) -> None:
        self._config_dir = directory

    def sync(self) -> dict[str, list[str]]:
        discovered: list[str] = []
        reconnected: list[str] = []
        if self._config_dir:
            configs = MCPServerConfig.load_from_directory(self._config_dir)
            for cfg in configs:
                if not cfg.enabled:
                    if cfg.name in self._clients:
                        self.remove_server(cfg.name)
                    continue
                existing = self._clients.get(cfg.name)
                if existing is None:
                    try:
                        self.add_server(cfg)
                        discovered.append(cfg.name)
                    except Exception:
                        pass
                elif not existing.is_connected():
                    try:
                        existing.disconnect()
                        if self._trust is not None:
                            status = self._trust.stage_server(cfg)
                            self._pending_configs[cfg.name] = cfg
                            if status != "trusted":
                                self.remove_server(cfg.name)
                                continue
                        self._connect_server(cfg)
                        reconnected.append(cfg.name)
                    except Exception:
                        pass
        return {"discovered": discovered, "reconnected": reconnected}

    def list_servers(self) -> list[dict[str, Any]]:
        connected = [
            {
                "name": name,
                "tools": client.tools,
                "connected": client.is_connected(),
            }
            for name, client in self._clients.items()
        ]
        if self._trust is None:
            return connected
        by_name = {str(item["name"]): item for item in connected}
        for record in self._trust.list_servers():
            name = str(record["name"])
            item = by_name.setdefault(name, {"name": name, "tools": [], "connected": False})
            item["trust_status"] = record["trust_status"]
            item["tool_grants"] = self._trust.list_tool_grants(name)
        return list(by_name.values())

    def _make_mcp_invoker(self, server_name: str, tool_name: str) -> Callable[..., ToolResult]:
        def invoke(**kwargs: object) -> ToolResult:
            client = self._clients.get(server_name)
            if not client:
                return ToolResult(status="error", error="MCP server not connected")
            result = client.call_tool(tool_name, {k: v for k, v in kwargs.items()})
            if "error" in result:
                return ToolResult(status="error", error=str(result["error"]))
            content_list = result.get("content", [{}])
            if isinstance(content_list, list) and content_list:
                text = str(content_list[0].get("text", ""))
            else:
                text = str(result)
            return ToolResult(status="ok", summary=text)

        return invoke

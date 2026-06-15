from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.shared import CapabilityManifest, CapabilityType, RiskLevel

from .client import MCPClient
from .server import MCPServerConfig


class MCPServerManager:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._cap_reg = capability_registry

    def add_server(self, config: MCPServerConfig) -> None:
        client = MCPClient(config)
        client.connect()
        self._clients[config.name] = client
        for tool in client.tools:
            tool_name: str = str(tool.get("name", "unknown"))
            mcp_tool_name = f"mcp_{config.name}_{tool_name}"
            manifest = CapabilityManifest(
                name=mcp_tool_name,
                version="1.0.0",
                type=CapabilityType.tool,
                description=str(tool.get("description", "")),
                input_schema=tool.get("inputSchema", {}),
                output_schema={},
                permissions=[],
                risk_level=RiskLevel.low,
                allowed_contexts=["interactive", "background"],
                approval_required=False,
                audit_required=False,
                idempotent=False,
            )
            self._cap_reg.register(
                mcp_tool_name,
                manifest,
                self._make_mcp_invoker(config.name, tool_name),
            )

    def remove_server(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client:
            client.disconnect()

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "tools": client.tools,
                "connected": client._process is not None,
            }
            for name, client in self._clients.items()
        ]

    def _make_mcp_invoker(
        self, server_name: str, tool_name: str
    ) -> Callable[..., ToolResult]:
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

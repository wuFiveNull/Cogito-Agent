from __future__ import annotations

from typing import Any, Protocol

from cogito_agent.mcp.server import MCPServerConfig


class MCPManagerPort(Protocol):
    def add_server(self, config: MCPServerConfig) -> None: ...
    def remove_server(self, name: str) -> None: ...
    def list_servers(self) -> list[dict[str, Any]]: ...
    def trust_server(self, name: str) -> bool: ...
    def block_server(self, name: str) -> bool: ...
    def grant_tool(
        self,
        server_name: str,
        tool_name: str,
        *,
        schema_hash: str,
        allowed_sources: list[str] | None = None,
        requires_approval: bool = True,
    ) -> bool: ...
    def revoke_tool(self, server_name: str, tool_name: str) -> bool: ...
    def sync(self) -> dict[str, list[str]]: ...


class MCPAuditPort(Protocol):
    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
        redact_details: bool = True,
    ) -> str: ...


class MCPCallReaderPort(Protocol):
    def list_recent(
        self,
        server_name: str,
        limit: int = 20,
    ) -> list[dict[str, object]]: ...


class MCPApplicationService:
    _ALLOWED_SOURCES = {"interactive", "scheduler", "skill", "drift", "webhook"}

    def __init__(
        self,
        manager: MCPManagerPort,
        audit: MCPAuditPort | None = None,
        call_reader: MCPCallReaderPort | None = None,
    ) -> None:
        self._manager = manager
        self._audit = audit
        self._call_reader = call_reader

    def list_servers(self) -> list[dict[str, Any]]:
        return self._manager.list_servers()

    def list_recent_calls(
        self,
        server_name: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        if self._call_reader is None:
            return []
        return self._call_reader.list_recent(server_name, limit)

    def add(
        self,
        config: MCPServerConfig,
        *,
        name: str,
        workspace_id: str,
        actor_id: str = "api",
    ) -> None:
        self._manager.add_server(config)
        self._audit_change(actor_id, workspace_id, name, "mcp.server.stage", True)

    def remove(
        self,
        name: str,
        *,
        workspace_id: str,
        actor_id: str = "api",
    ) -> None:
        self._manager.remove_server(name)
        self._audit_change(actor_id, workspace_id, name, "mcp.server.disconnect", True)

    def trust(self, name: str, *, workspace_id: str, actor_id: str = "console") -> bool:
        changed = self._manager.trust_server(name)
        self._audit_change(actor_id, workspace_id, name, "mcp.server.trust", changed)
        return changed

    def block(self, name: str, *, workspace_id: str, actor_id: str = "console") -> bool:
        changed = self._manager.block_server(name)
        self._audit_change(actor_id, workspace_id, name, "mcp.server.block", changed)
        return changed

    def grant(
        self,
        server_name: str,
        tool_name: str,
        *,
        schema_hash: str,
        allowed_sources: list[str],
        requires_approval: bool,
        workspace_id: str,
        actor_id: str = "console",
    ) -> bool:
        sources = sorted(set(allowed_sources) & self._ALLOWED_SOURCES)
        if not sources:
            sources = ["interactive"]
        changed = self._manager.grant_tool(
            server_name,
            tool_name,
            schema_hash=schema_hash,
            allowed_sources=sources,
            requires_approval=requires_approval,
        )
        self._audit_change(
            actor_id,
            workspace_id,
            f"{server_name}/{tool_name}",
            "mcp.tool.grant",
            changed,
        )
        return changed

    def revoke(
        self,
        server_name: str,
        tool_name: str,
        *,
        workspace_id: str,
        actor_id: str = "console",
    ) -> bool:
        changed = self._manager.revoke_tool(server_name, tool_name)
        self._audit_change(
            actor_id,
            workspace_id,
            f"{server_name}/{tool_name}",
            "mcp.tool.revoke",
            changed,
        )
        return changed

    def sync(self) -> dict[str, list[str]]:
        return self._manager.sync()

    def _audit_change(
        self,
        actor_id: str,
        workspace_id: str,
        resource: str,
        action: str,
        changed: bool,
    ) -> None:
        if self._audit is None:
            return
        self._audit.log(
            actor_id=actor_id,
            action=action,
            resource=resource,
            workspace_id=workspace_id,
            decision="allow" if changed else "deny",
            reason="state changed" if changed else "target missing or stale schema",
        )

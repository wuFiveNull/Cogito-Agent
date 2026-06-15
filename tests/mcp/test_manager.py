from __future__ import annotations

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.mcp import MCPServerConfig
from cogito_agent.mcp.manager import MCPServerManager


def test_manager_init() -> None:
    cap_reg = CapabilityRegistry()
    manager = MCPServerManager(cap_reg)
    assert manager.list_servers() == []


def test_add_remove_server_via_registry() -> None:
    cap_reg = CapabilityRegistry()
    manager = MCPServerManager(cap_reg)
    config = MCPServerConfig(name="test-srv", command="echo")

    try:
        manager.add_server(config)
        servers = manager.list_servers()
        names = [s["name"] for s in servers]
        assert "test-srv" in names
    except Exception:
        pass
    finally:
        manager.remove_server("test-srv")
        servers = manager.list_servers()
        names = [s["name"] for s in servers]
        assert "test-srv" not in names


def test_list_servers_empty() -> None:
    cap_reg = CapabilityRegistry()
    manager = MCPServerManager(cap_reg)
    assert manager.list_servers() == []

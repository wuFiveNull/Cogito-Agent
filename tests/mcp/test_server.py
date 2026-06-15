from __future__ import annotations

from cogito_agent.mcp import MCPServerConfig


def test_server_config_defaults() -> None:
    cfg = MCPServerConfig(name="test", command="python")
    assert cfg.name == "test"
    assert cfg.command == "python"
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.enabled is True


def test_server_config_with_args() -> None:
    cfg = MCPServerConfig(
        name="fs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
        env={"KEY": "val"},
    )
    assert cfg.name == "fs"
    assert "server-filesystem" in cfg.args[1]


def test_server_config_disabled() -> None:
    cfg = MCPServerConfig(name="off", command="echo", enabled=False)
    assert cfg.enabled is False

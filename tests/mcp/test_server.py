from __future__ import annotations

import json
import tempfile
from pathlib import Path

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


def test_load_from_directory_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        configs = MCPServerConfig.load_from_directory(tmp)
        assert configs == []


def test_load_from_directory_nonexistent() -> None:
    configs = MCPServerConfig.load_from_directory(r"C:\nonexistent_mcp_dir_xyz")
    assert configs == []


def test_load_from_directory_single_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg_data = {"name": "srv1", "command": "echo", "args": ["hello"]}
        Path(tmp, "srv1.json").write_text(json.dumps(cfg_data), encoding="utf-8")
        configs = MCPServerConfig.load_from_directory(tmp)
        assert len(configs) == 1
        assert configs[0].name == "srv1"
        assert configs[0].command == "echo"
        assert configs[0].args == ["hello"]


def test_load_from_directory_multiple_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "a.json").write_text(
            json.dumps({"name": "alpha", "command": "echo"}), encoding="utf-8"
        )
        Path(tmp, "b.json").write_text(
            json.dumps({"name": "beta", "command": "cat"}), encoding="utf-8"
        )
        configs = MCPServerConfig.load_from_directory(tmp)
        assert len(configs) == 2
        assert {c.name for c in configs} == {"alpha", "beta"}


def test_load_from_directory_skips_non_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "srv.json").write_text(
            json.dumps({"name": "srv", "command": "echo"}), encoding="utf-8"
        )
        Path(tmp, "ignore.yaml").write_text("name: x", encoding="utf-8")
        Path(tmp, "ignore.txt").write_text("hello", encoding="utf-8")
        configs = MCPServerConfig.load_from_directory(tmp)
        assert len(configs) == 1


def test_load_from_directory_invalid_json_skipped() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "bad.json").write_text("not json", encoding="utf-8")
        Path(tmp, "good.json").write_text(
            json.dumps({"name": "good", "command": "echo"}), encoding="utf-8"
        )
        configs = MCPServerConfig.load_from_directory(tmp)
        assert len(configs) == 1
        assert configs[0].name == "good"


def test_load_from_directory_json_list() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = [
            {"name": "srv1", "command": "echo"},
            {"name": "srv2", "command": "cat"},
        ]
        Path(tmp, "servers.json").write_text(json.dumps(data), encoding="utf-8")
        configs = MCPServerConfig.load_from_directory(tmp)
        assert len(configs) == 2
        assert {c.name for c in configs} == {"srv1", "srv2"}

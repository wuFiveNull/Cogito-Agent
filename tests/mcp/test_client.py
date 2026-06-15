from __future__ import annotations

import subprocess
import sys

from cogito_agent.mcp import MCPClient, MCPServerConfig


def test_is_connected_false_no_process() -> None:
    cfg = MCPServerConfig(name="test", command="echo")
    client = MCPClient(cfg)
    assert client.is_connected() is False


def test_ping_no_process() -> None:
    cfg = MCPServerConfig(name="test", command="echo")
    client = MCPClient(cfg)
    assert client.ping() is False


def test_is_connected_with_process() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    cfg = MCPServerConfig(name="test", command="echo")
    client = MCPClient(cfg)
    client._process = proc
    try:
        assert client.is_connected() is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)

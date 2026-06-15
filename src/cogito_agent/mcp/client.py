from __future__ import annotations

import json
import subprocess
import uuid
from typing import Any

from .server import MCPServerConfig


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[str] | None = None
        self._tools: list[dict[str, Any]] = []

    def connect(self) -> None:
        env = {**self._config.env} if self._config.env else None
        self._process = subprocess.Popen(
            [self._config.command, *self._config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        resp = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "cogito-agent", "version": "0.1.0"},
        })
        if resp and "result" in resp:
            self._send_notification("initialized")

        tools_resp = self._send_request("tools/list", {})
        if tools_resp and "result" in tools_resp:
            self._tools = tools_resp["result"].get("tools", [])

    def disconnect(self) -> None:
        if self._process:
            if self._process.stdin:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    def is_connected(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ping(self) -> bool:
        if not self.is_connected():
            return False
        resp = self._send_request("ping", {})
        return resp is not None and "result" in resp

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp and "result" in resp:
            result = resp["result"]
            return dict(result) if isinstance(result, dict) else {"data": str(result)}
        return {"error": "No response from MCP server"}

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        req = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        line = json.dumps(req) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        resp_line = self._process.stdout.readline()
        if resp_line:
            try:
                parsed: dict[str, Any] = json.loads(resp_line.strip())
                return parsed
            except json.JSONDecodeError:
                return None
        return None

    def _send_notification(self, method: str) -> None:
        if not self._process or not self._process.stdin:
            return
        notif = {
            "jsonrpc": "2.0",
            "method": method,
        }
        self._process.stdin.write(json.dumps(notif) + "\n")
        self._process.stdin.flush()

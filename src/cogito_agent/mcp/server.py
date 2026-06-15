from __future__ import annotations

from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    enabled: bool = True

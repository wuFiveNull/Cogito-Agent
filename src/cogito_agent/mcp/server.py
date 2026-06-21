from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = None
    enabled: bool = True

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"enabled"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def load_from_directory(cls, directory: str) -> list[MCPServerConfig]:
        configs: list[MCPServerConfig] = []
        path = Path(directory)
        if not path.is_dir():
            return configs
        for entry in sorted(path.iterdir()):
            if entry.suffix not in (".json",):
                continue
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        configs.append(cls(**item))
                else:
                    configs.append(cls(**data))
            except Exception:
                continue
        return configs

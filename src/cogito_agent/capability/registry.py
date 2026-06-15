from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cogito_agent.shared import CapabilityManifest


class ToolResult:
    def __init__(
        self,
        status: str = "ok",
        summary: str = "",
        data: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        self.status = status
        self.summary = summary
        self.data = data or {}
        self.error = error


class CapabilityRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[CapabilityManifest, Callable[..., ToolResult]]] = {}

    def register(
        self, name: str, manifest: CapabilityManifest,
        invoke_fn: Callable[..., ToolResult],
    ) -> None:
        self._tools[name] = (manifest, invoke_fn)

    def get_manifest(self, name: str) -> CapabilityManifest | None:
        entry = self._tools.get(name)
        if entry is None:
            return None
        return entry[0]

    def invoke(self, name: str, **kwargs: Any) -> ToolResult | None:
        entry = self._tools.get(name)
        if entry is None:
            return None
        _, invoke_fn = entry
        return invoke_fn(**kwargs)

    def list_tools(self) -> list[CapabilityManifest]:
        return [m for m, _ in self._tools.values()]

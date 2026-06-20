from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from fastapi import Request

from cogito_agent.console.context import ConsolePageContext


class BaseConsoleService(ABC):
    @abstractmethod
    def build_page_context(
        self,
        request: Request,
        title: str,
        extra: dict[str, object] | None = None,
    ) -> ConsolePageContext:
        ...

    @abstractmethod
    def get_version(self) -> str:
        ...

    @abstractmethod
    def get_system_status(self) -> dict[str, Any]:
        ...

from __future__ import annotations

from typing import Protocol


class DriftControlPort(Protocol):
    def pause(self, reason: str = "") -> None: ...
    def resume(self) -> None: ...


class DriftApplicationService:
    def __init__(self, runtime: DriftControlPort) -> None:
        self._runtime = runtime

    def pause(self, reason: str = "") -> None:
        self._runtime.pause(reason)

    def resume(self) -> None:
        self._runtime.resume()

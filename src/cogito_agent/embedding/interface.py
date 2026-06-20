from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


class EmbeddingHealth:
    def __init__(
        self,
        healthy: bool,
        provider_name: str = "",
        model_name: str = "",
        dimension: int = 0,
        is_semantic: bool = False,
        error_message: str = "",
    ) -> None:
        self.healthy = healthy
        self.provider_name = provider_name
        self.model_name = model_name
        self.dimension = dimension
        self.is_semantic = is_semantic
        self.error_message = error_message

    def __repr__(self) -> str:
        status = "healthy" if self.healthy else "unhealthy"
        return (
            f"EmbeddingHealth({status}, provider={self.provider_name}, "
            f"model={self.model_name}, dim={self.dimension}, "
            f"semantic={self.is_semantic})"
        )


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def is_semantic(self) -> bool: ...

    def embed_text(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...

    def health_check(self) -> EmbeddingHealth: ...

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from .interface import EmbeddingHealth


class MockEmbeddingProvider:
    """Deterministic hash-based embedding for testing only.

    This MUST NOT be used as a runtime fallback for failed API calls.
    It is only for unit tests or explicit 'provider: mock' configuration.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_semantic(self) -> bool:
        return False

    def embed_text(self, text: str) -> list[float]:
        return self._hash_encode(text)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._hash_encode(t) for t in texts]

    def _hash_encode(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self._dimension):
            idx = i % len(h)
            val = (h[idx] - 128) / 128.0
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def health_check(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            healthy=True,
            provider_name=self.provider_name,
            model_name=self.model_name,
            dimension=self._dimension,
            is_semantic=False,
        )

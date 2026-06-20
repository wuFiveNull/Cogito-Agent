from __future__ import annotations

import logging
from collections.abc import Sequence

from .interface import EmbeddingHealth

logger = logging.getLogger(__name__)


class LocalSentenceTransformerEmbeddingProvider:
    """Local embedding using sentence-transformers (optional dependency)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None
        self._dimension = 384

    @property
    def provider_name(self) -> str:
        return "local_sentence_transformer"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_semantic(self) -> bool:
        return True

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(self._model_name)
            self._model = model
            self._dimension = model.get_sentence_embedding_dimension()
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install with: pip install cogito-agent[vector]"
            )

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        self._load_model()
        assert self._model is not None
        embeddings = self._model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False,
        )
        return [e.tolist() for e in embeddings]

    def health_check(self) -> EmbeddingHealth:
        try:
            self.embed_text("health check")
            return EmbeddingHealth(
                healthy=True,
                provider_name=self.provider_name,
                model_name=self._model_name,
                dimension=self._dimension,
                is_semantic=True,
            )
        except Exception as e:
            return EmbeddingHealth(
                healthy=False,
                error_message=str(e),
                provider_name=self.provider_name,
                model_name=self._model_name,
                dimension=self._dimension,
            )

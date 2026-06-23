from typing import Protocol, runtime_checkable

from .dense import DenseMemoryRetriever
from .fusion import CandidateFusion, ScoreBreakdown
from .gate import RetrievalGate, RetrievalGateResult
from .injection import MemoryInjectionBuilder
from .query import MemoryQueryBuilder, MemoryQueryContext
from .resident import ResidentMemorySelector
from .service import MemoryRecallResult, MemoryRetrievalService
from .sparse import SparseMemoryRetriever


@runtime_checkable
class MemoryRetrievalPort(Protocol):
    """Protocol for the memory retrieval service.

    Any implementation must provide a ``recall()`` method that accepts
    a query context and returns results with scored memory items.
    """

    def recall(
        self,
        query_context: MemoryQueryContext,
        limit: int = 10,
        include_archived: bool = False,
        force_mode: str = "",
    ) -> MemoryRecallResult: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Protocol for text embedding providers."""

    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    @property
    def is_semantic(self) -> bool: ...

    def embed_text(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


__all__ = [
    "MemoryRetrievalService",
    "MemoryRecallResult",
    "MemoryQueryBuilder",
    "MemoryQueryContext",
    "RetrievalGate",
    "RetrievalGateResult",
    "SparseMemoryRetriever",
    "DenseMemoryRetriever",
    "ResidentMemorySelector",
    "CandidateFusion",
    "ScoreBreakdown",
    "MemoryInjectionBuilder",
    "MemoryRetrievalPort",
    "EmbeddingPort",
]

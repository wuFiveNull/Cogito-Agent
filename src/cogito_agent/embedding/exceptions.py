from __future__ import annotations


class EmbeddingError(Exception):
    pass


class EmbeddingConfigurationError(EmbeddingError):
    pass


class EmbeddingAuthenticationError(EmbeddingError):
    pass


class EmbeddingRateLimitError(EmbeddingError):
    pass


class EmbeddingTimeoutError(EmbeddingError):
    pass


class EmbeddingAPIError(EmbeddingError):
    def __init__(self, message: str, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


class EmbeddingResponseError(EmbeddingError):
    pass


class EmbeddingDimensionMismatchError(EmbeddingError):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Embedding dimension mismatch: expected {expected}, got {actual}")

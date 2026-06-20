from __future__ import annotations

import json
import logging
import math
import random
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import urljoin

import httpx

from .exceptions import (
    EmbeddingAPIError,
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingDimensionMismatchError,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
)
from .interface import EmbeddingHealth, EmbeddingProvider
from .registry import MODEL_REGISTRY, get_model_info

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_NON_RETRYABLE_STATUSES = {400, 401, 403, 404}


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        expected_dimension: int = 0,
        encoding_format: str = "float",
        timeout_seconds: float = 30.0,
        connect_timeout_seconds: float = 10.0,
        max_retries: int = 3,
        batch_size: int = 32,
        normalize: bool = True,
        verify_norm: bool = True,
        max_input_tokens: int = 8192,
        http_client: Any = None,
    ) -> None:
        if not base_url:
            raise EmbeddingConfigurationError("base_url is required")
        self._base_url = base_url.rstrip("/")
        if not self._base_url.endswith("/v1"):
            self._base_url += "/v1"
        self._model = model
        self._api_key = api_key
        self._expected_dimension = expected_dimension
        self._encoding_format = encoding_format
        self._timeout_seconds = timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_retries = max_retries
        self._batch_size = min(batch_size, 64)
        self._normalize = normalize
        self._verify_norm = verify_norm
        self._max_input_tokens = max_input_tokens
        self._http_client = http_client
        self._own_client: httpx.Client | None = None

        if not self._expected_dimension:
            info = get_model_info(model)
            if info:
                self._expected_dimension = info.dimension
                if not max_input_tokens or max_input_tokens == 8192:
                    self._max_input_tokens = info.max_input_tokens
            else:
                raise EmbeddingConfigurationError(
                    f"Model '{model}' not in registry; "
                    "please set expected_dimension explicitly"
                )

        if self._expected_dimension <= 0:
            raise EmbeddingConfigurationError(
                "expected_dimension must be a positive integer"
            )

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    @property
    def is_semantic(self) -> bool:
        return True

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        result: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = list(texts[i : i + self._batch_size])
            result.extend(self._call_api(batch))
        return result

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        url = urljoin(self._base_url + "/", "embeddings")
        body: dict[str, object] = {
            "model": self._model,
            "input": texts,
            "encoding_format": self._encoding_format,
        }

        model_info = get_model_info(self._model)
        if model_info and model_info.supports_dimensions_parameter:
            body["dimensions"] = self._expected_dimension

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        for attempt in range(1 + self._max_retries):
            try:
                resp_data = self._do_request(url, headers, body, attempt)
                return self._parse_response(resp_data, texts)
            except EmbeddingAuthenticationError:
                raise
            except EmbeddingConfigurationError:
                raise
            except EmbeddingRateLimitError as e:
                if attempt >= self._max_retries:
                    raise
                retry_after = getattr(e, "retry_after", None)
                delay = self._backoff_delay(attempt, retry_after)
                logger.warning(
                    "Rate limited, retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, self._max_retries,
                )
                time.sleep(delay)
            except EmbeddingTimeoutError:
                if attempt >= self._max_retries:
                    raise
                delay = self._backoff_delay(attempt)
                time.sleep(delay)
            except EmbeddingAPIError as e:
                if e.status_code in _NON_RETRYABLE_STATUSES:
                    raise
                if attempt >= self._max_retries:
                    raise
                delay = self._backoff_delay(attempt)
                time.sleep(delay)
            except EmbeddingResponseError:
                if attempt >= self._max_retries:
                    raise
                delay = self._backoff_delay(attempt)
                time.sleep(delay)

        raise EmbeddingAPIError(
            f"Embedding API call failed after {self._max_retries + 1} attempts",
            status_code=0,
        )

    def _get_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        if self._own_client is None:
            self._own_client = httpx.Client(
                timeout=httpx.Timeout(
                    self._timeout_seconds,
                    connect=self._connect_timeout_seconds,
                ),
            )
        return self._own_client

    def close(self) -> None:
        if self._own_client is not None:
            self._own_client.close()
            self._own_client = None

    def _do_request(
        self, url: str, headers: dict[str, str],
        body: dict[str, object], attempt: int,
    ) -> Any:
        client = self._get_client()
        try:
            resp = client.post(
                url, headers=headers, json=body,
            )
        except httpx.TimeoutException as e:
            raise EmbeddingTimeoutError(str(e)) from e
        except httpx.ConnectError as e:
            raise EmbeddingTimeoutError(f"Connection failed: {e}") from e
        except Exception as e:
            raise EmbeddingAPIError(str(e), status_code=0) from e

        if resp.status_code == 429:
            retry_after = None
            try:
                retry_after = int(resp.headers.get("Retry-After", "0"))
            except (ValueError, TypeError):
                pass
            safe_msg = _safe_error_message(resp.text)
            err = EmbeddingRateLimitError(safe_msg)
            err.retry_after = retry_after  # type: ignore[attr-defined]
            raise err

        if resp.status_code == 401:
            raise EmbeddingAuthenticationError("Authentication failed (401)")
        if resp.status_code == 403:
            raise EmbeddingAuthenticationError("Access denied (403)")
        if resp.status_code == 404:
            raise EmbeddingAPIError("Endpoint not found (404)", status_code=404)
        if resp.status_code == 400:
            raise EmbeddingAPIError(
                _safe_error_message(resp.text), status_code=400,
            )
        if resp.status_code >= 500:
            raise EmbeddingAPIError(
                f"Server error ({resp.status_code})", status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise EmbeddingAPIError(
                f"Unexpected status {resp.status_code}", status_code=resp.status_code,
            )

        try:
            return resp.json()
        except Exception as e:
            raise EmbeddingResponseError(f"Invalid JSON response: {e}") from e

    def _parse_response(
        self, resp_data: Any, texts: list[str],
    ) -> list[list[float]]:
        if not isinstance(resp_data, dict):
            raise EmbeddingResponseError("Response is not a JSON object")

        data = resp_data.get("data")
        if not isinstance(data, list):
            raise EmbeddingResponseError("Response.data is missing or not a list")

        if len(data) == 0:
            raise EmbeddingResponseError("Response.data is empty")

        indexed: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingResponseError("Response.data item is not an object")
            idx = item.get("index")
            if not isinstance(idx, int):
                raise EmbeddingResponseError("Response.data item missing integer index")
            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise EmbeddingResponseError(
                    f"Response.data[{idx}].embedding is missing or not a list"
                )
            indexed[idx] = [float(v) for v in embedding]

        result: list[list[float]] = []
        for i in range(len(texts)):
            vec = indexed.get(i)
            if vec is None:
                raise EmbeddingResponseError(
                    f"Response missing embedding for index {i}"
                )
            self._validate_vector(vec, i)
            result.append(vec)

        return result

    def _validate_vector(self, vec: list[float], index: int) -> None:
        if len(vec) != self._expected_dimension:
            raise EmbeddingDimensionMismatchError(self._expected_dimension, len(vec))
        for v in vec:
            if not isinstance(v, float):
                raise EmbeddingResponseError(
                    f"Non-float value at index {index}: {type(v).__name__}"
                )
            if math.isnan(v) or math.isinf(v):
                raise EmbeddingResponseError(
                    f"Invalid value (NaN/Inf) at index {index}"
                )

        norm = math.sqrt(sum(x * x for x in vec))
        if norm <= 1e-12:
            raise EmbeddingResponseError(
                f"Embedding vector at index {index} has zero norm"
            )

        if self._normalize:
            vec[:] = [x / norm for x in vec]
        elif self._verify_norm and abs(norm - 1.0) > 0.01:
            raise EmbeddingResponseError(
                f"Embedding at index {index} norm={norm:.4f}, expected ~1.0"
            )

    def _backoff_delay(
        self, attempt: int, retry_after: int | None = None,
    ) -> float:
        if retry_after and retry_after > 0:
            return float(retry_after) + random.uniform(0, 1)
        base = 1.0
        delay = base * (2 ** attempt)
        jitter = random.uniform(0, delay * 0.5)
        result = delay + jitter
        return min(result, 60.0)  # type: ignore[no-any-return]

    def health_check(self) -> EmbeddingHealth:
        try:
            vec = self.embed_text("health check")
            if len(vec) != self._expected_dimension:
                return EmbeddingHealth(
                    healthy=False,
                    provider_name=self.provider_name,
                    model_name=self._model,
                    dimension=self._expected_dimension,
                    is_semantic=self.is_semantic,
                    error_message=(
                        f"Returned {len(vec)} dimensions, expected {self._expected_dimension}"
                    ),
                )
            return EmbeddingHealth(
                healthy=True,
                provider_name=self.provider_name,
                model_name=self._model,
                dimension=self._expected_dimension,
                is_semantic=self.is_semantic,
            )
        except EmbeddingAuthenticationError as e:
            return EmbeddingHealth(
                healthy=False, error_message=str(e),
                provider_name=self.provider_name, model_name=self._model,
                dimension=self._expected_dimension,
            )
        except Exception as e:
            return EmbeddingHealth(
                healthy=False, error_message=str(e),
                provider_name=self.provider_name, model_name=self._model,
                dimension=self._expected_dimension,
            )


def _safe_error_message(text: str) -> str:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            msg = data.get("error", {}).get("message", str(data))
            if isinstance(msg, str):
                return msg[:200]
    except Exception:
        pass
    return "API error"

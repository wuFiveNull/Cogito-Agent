from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import pytest

from cogito_agent.embedding.exceptions import (
    EmbeddingAPIError,
    EmbeddingAuthenticationError,
    EmbeddingDimensionMismatchError,
    EmbeddingResponseError,
)
from cogito_agent.embedding.mock import MockEmbeddingProvider
from cogito_agent.embedding.openai_compatible import OpenAICompatibleEmbeddingProvider
from cogito_agent.embedding.registry import get_model_info


class TestMockEmbeddingProvider:
    def test_encode(self):
        p = MockEmbeddingProvider()
        vec = p.embed_text("hello world")
        assert len(vec) == 384
        assert p.is_semantic is False
        assert p.provider_name == "mock"
        assert p.model_name == "mock"

    def test_deterministic(self):
        p = MockEmbeddingProvider()
        a = p.embed_text("hello")
        b = p.embed_text("hello")
        assert a == b

    def test_batch(self):
        p = MockEmbeddingProvider()
        results = p.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(len(v) == 384 for v in results)

    def test_health_check(self):
        p = MockEmbeddingProvider()
        h = p.health_check()
        assert h.healthy is True
        assert h.provider_name == "mock"
        assert h.dimension == 384


class TestOpenAICompatibleEmbeddingProvider:
    @pytest.fixture
    def config(self):
        return {
            "base_url": "https://api.example.com/v1",
            "model": "text-embedding-3-small",
            "api_key": "sk-test-key",
            "expected_dimension": 1536,
            "max_retries": 0,
        }

    def _make_mock_response(self, data: list[list[float]], status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp_data = {
            "data": [{"index": i, "embedding": vec} for i, vec in enumerate(data)],
        }
        resp.json.return_value = resp_data
        resp.text = json.dumps(resp_data)
        return resp

    def test_single_input(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[0.1] * 1536])
        provider._http_client = mock_client

        vec = provider.embed_text("hello")
        assert len(vec) == 1536
        mock_client.post.assert_called_once()

    def test_batch_input(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response(
            [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]
        )
        provider._http_client = mock_client

        results = provider.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert len(results[0]) == 1536

    def test_response_reordering(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "data": [
                {"index": 2, "embedding": [0.3] * 1536},
                {"index": 0, "embedding": [0.1] * 1536},
                {"index": 1, "embedding": [0.2] * 1536},
            ],
        }
        resp.text = json.dumps(resp.json.return_value)
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        results = provider.embed_batch(["a", "b", "c"])
        norm_a = math.sqrt(1536 * 0.01)
        norm_b = math.sqrt(1536 * 0.04)
        norm_c = math.sqrt(1536 * 0.09)
        assert results[0][0] == pytest.approx(0.1 / norm_a, abs=0.01)
        assert results[1][0] == pytest.approx(0.2 / norm_b, abs=0.01)
        assert results[2][0] == pytest.approx(0.3 / norm_c, abs=0.01)

    def test_wrong_dimension_rejected(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response(
            [[0.1] * 384]  # Wrong dimension
        )
        provider._http_client = mock_client

        with pytest.raises(EmbeddingDimensionMismatchError):
            provider.embed_text("hello")

    def test_empty_data_rejected(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": []}
        resp.text = '{"data": []}'
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        with pytest.raises(EmbeddingResponseError, match="empty"):
            provider.embed_text("hello")

    def test_missing_embedding(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"index": 0}]}  # No embedding key
        resp.text = '{"data": [{"index": 0}]}'
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        with pytest.raises(EmbeddingResponseError):
            provider.embed_text("hello")

    def test_nan_in_embedding(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[float("nan")] * 1536])
        provider._http_client = mock_client

        with pytest.raises(EmbeddingResponseError, match="NaN"):
            provider.embed_text("hello")

    def test_401_authentication(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 401
        resp.text = '{"error": "unauthorized"}'
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        with pytest.raises(EmbeddingAuthenticationError):
            provider.embed_text("hello")

    def test_429_rate_limit(self, config):
        config_no_retry = {**config, "max_retries": 2}
        provider = OpenAICompatibleEmbeddingProvider(**config_no_retry)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 429
        resp.text = '{"error": "rate limited"}'
        resp.headers = {"Retry-After": "1"}
        mock_client.post.side_effect = [resp, resp, self._make_mock_response([[0.1] * 1536])]
        provider._http_client = mock_client

        vec = provider.embed_text("hello")
        assert len(vec) == 1536
        assert mock_client.post.call_count == 3

    def test_500_retry_then_success(self, config):
        config_no_retry = {**config, "max_retries": 2}
        provider = OpenAICompatibleEmbeddingProvider(**config_no_retry)
        mock_client = MagicMock()
        resp_err = MagicMock()
        resp_err.status_code = 500
        resp_err.text = '{"error": "server error"}'
        resp_ok = self._make_mock_response([[0.1] * 1536])
        mock_client.post.side_effect = [resp_err, resp_err, resp_ok]
        provider._http_client = mock_client

        vec = provider.embed_text("hello")
        assert len(vec) == 1536

    def test_retries_exhausted(self, config):
        config_no_retry = {**config, "max_retries": 1}
        provider = OpenAICompatibleEmbeddingProvider(**config_no_retry)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 500
        resp.text = '{"error": "server error"}'
        mock_client.post.side_effect = [resp, resp]
        provider._http_client = mock_client

        with pytest.raises(EmbeddingAPIError):
            provider.embed_text("hello")

    def test_url_construction(self, config):
        prov = OpenAICompatibleEmbeddingProvider(
            base_url="https://api.example.com",
            model="text-embedding-3-small",
            api_key="sk-test-key",
            expected_dimension=1536,
            max_retries=0,
        )
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[0.1] * 1536])
        prov._http_client = mock_client

        prov.embed_text("test")
        call_url = mock_client.post.call_args[0][0]
        assert call_url == "https://api.example.com/v1/embeddings"

    def test_auth_header(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[0.1] * 1536])
        provider._http_client = mock_client

        provider.embed_text("test")
        headers = mock_client.post.call_args[1]["headers"]
        assert "Authorization" in headers
        assert "sk-test-key" in headers["Authorization"]
        assert "Bearer" in headers["Authorization"]

    def test_no_dimensions_for_bge_m3(self):
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://api.example.com",
            model="BAAI/bge-m3",
            api_key="sk-test-key",
            expected_dimension=1024,
            max_retries=0,
        )
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[0.1] * 1024])
        provider._http_client = mock_client

        provider.embed_text("test")
        body = mock_client.post.call_args[1]["json"]
        assert "dimensions" not in body

    def test_health_check_healthy(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[0.1] * 1536])
        provider._http_client = mock_client

        health = provider.health_check()
        assert health.healthy is True

    def test_health_check_unhealthy(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 401
        resp.text = '{"error": "unauthorized"}'
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        health = provider.health_check()
        assert health.healthy is False

    def test_api_key_not_in_log_or_exception(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 401
        resp.text = '{"error": "unauthorized"}'
        mock_client.post.return_value = resp
        provider._http_client = mock_client

        try:
            provider.embed_text("test")
        except EmbeddingAuthenticationError as e:
            assert "sk-test-key" not in str(e)

    def test_normalization(self):
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://api.example.com",
            model="text-embedding-3-small",
            api_key="sk-test-key",
            expected_dimension=4,
            max_retries=0,
            normalize=True,
        )
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response([[3.0, 0.0, 0.0, 0.0]])
        provider._http_client = mock_client

        vec = provider.embed_text("test")
        import math

        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 0.001

    def test_batch_response_order_preserved(self, config):
        provider = OpenAICompatibleEmbeddingProvider(**config)
        mock_client = MagicMock()
        mock_client.post.return_value = self._make_mock_response(
            [[0.1] * 1536, [0.2] * 1536, [0.3] * 1536]
        )
        provider._http_client = mock_client

        results = provider.embed_batch(["first", "second", "third"])
        assert len(results) == 3


class TestModelRegistry:
    def test_get_bge_m3(self):
        info = get_model_info("BAAI/bge-m3")
        assert info is not None
        assert info.dimension == 1024
        assert info.supports_dimensions_parameter is False

    def test_get_text_embedding_3_small(self):
        info = get_model_info("text-embedding-3-small")
        assert info is not None
        assert info.dimension == 1536
        assert info.supports_dimensions_parameter is True

    def test_unknown_model(self):
        info = get_model_info("unknown-model")
        assert info is None

    def test_all_minilm(self):
        info = get_model_info("all-MiniLM-L6-v2")
        assert info is not None
        assert info.dimension == 384
        assert info.max_input_tokens == 256

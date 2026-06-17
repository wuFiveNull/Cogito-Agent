from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestConsoleAuth:
    @pytest.fixture(autouse=True)
    def _setup_teardown(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_no_auth_when_key_not_set(self) -> None:
        os.environ.pop("COGITO_API_KEY", None)
        resp = client.get("/console/")
        assert resp.status_code == 200

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get("/console/")
        assert resp.status_code == 401

    def test_auth_blocks_wrong_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get("/console/", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get("/console/", headers={"Authorization": "Bearer secret-test-key-123"})
        assert resp.status_code == 200

    def test_status_api_respects_auth_too(self) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get("/api/v1/status")
        assert resp.status_code == 401
        resp = client.get("/api/v1/status", headers={"Authorization": "Bearer secret-test-key-123"})
        assert resp.status_code == 200

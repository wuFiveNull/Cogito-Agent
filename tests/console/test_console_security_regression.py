from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)

ALL_CONSOLE_PAGES = [
    "/console/",
    "/console/chat",
    "/console/memory",
    "/console/approval",
    "/console/traces",
    "/console/audit",
    "/console/autonomy",
    "/console/config",
    "/console/doctor",
]

API_ENDPOINTS = [
    "/api/v1/status",
    "/api/v1/doctor",
]


class TestAuthRegression:
    @pytest.fixture(autouse=True)
    def _setup_teardown(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES + API_ENDPOINTS)
    def test_auth_blocks_no_token(self, path: str) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} should 401 without token"

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES + API_ENDPOINTS)
    def test_auth_allows_valid_token(self, path: str) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get(path, headers={"Authorization": "Bearer secret-test-key-123"})
        assert resp.status_code == 200, f"{path} should 200 with valid token"

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES)
    def test_auth_blocks_wrong_token(self, path: str) -> None:
        os.environ["COGITO_API_KEY"] = "secret-test-key-123"
        resp = client.get(path, headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401, f"{path} should 401 with wrong token"


class TestRedactionRegression:
    SECRET_VALUE_PATTERNS = ["password", "token_value"]

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES + API_ENDPOINTS)
    def test_no_secret_value_leak(self, path: str) -> None:
        resp = client.get(path)
        body = resp.text
        for pat in self.SECRET_VALUE_PATTERNS:
            if pat in body:
                idx = body.index(pat)
                ctx = body[max(0, idx-30):idx+len(pat)+30]
                pytest.fail(f"{path} contains '{pat}' in: ...{ctx}...")

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES + API_ENDPOINTS)
    def test_no_api_key_leak(self, path: str) -> None:
        import re
        resp = client.get(path)
        body = resp.text
        matches = re.findall(r"sk-[a-zA-Z0-9]{10,}", body)
        if matches:
            pytest.fail(f"{path} leaks API key pattern: {matches[0][:20]}...")

    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES + API_ENDPOINTS)
    def test_no_bearer_token_leak(self, path: str) -> None:
        import re
        resp = client.get(path)
        body = resp.text
        matches = re.findall(r"Bearer\s+[A-Za-z0-9\-._~+/]{8,}", body)
        if matches:
            pytest.fail(f"{path} leaks Bearer token: {matches[0][:30]}...")


class TestXSSRegression:
    @pytest.mark.parametrize("path", ALL_CONSOLE_PAGES)
    def test_no_stack_trace_in_html(self, path: str) -> None:
        resp = client.get(path)
        body = resp.text
        assert "Traceback" not in body, f"{path} leaks traceback"
        assert "File \"" not in body, f"{path} leaks file path"

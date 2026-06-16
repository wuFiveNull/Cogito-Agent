from __future__ import annotations

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from cogito_agent.api.app import app


def test_auth_disabled_no_key() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)
        resp = client.post("/chat", json={
            "text": "hello", "session_id": "sess", "workspace_id": "ws",
        })
        assert resp.status_code in (200, 404)


def test_auth_enabled_no_header() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        resp = client.post("/chat", json={
            "text": "hello", "session_id": "sess", "workspace_id": "ws",
        })
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "UNAUTHORIZED"


def test_auth_enabled_wrong_key() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={"text": "hello", "session_id": "sess", "workspace_id": "ws"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


def test_auth_enabled_correct_key() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        resp = client.post(
            "/chat",
            json={"text": "hello", "session_id": "sess", "workspace_id": "ws"},
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code in (200, 404)


def test_auth_protected_endpoints_without_key() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        endpoints = [
            ("GET", "/traces", {"workspace_id": "ws"}),
            ("GET", "/sessions", {"workspace_id": "ws"}),
            ("GET", "/workspaces", {}),
            ("POST", "/workspaces", {"name": "test"}),
            ("GET", "/memories", {"workspace_id": "ws"}),
            ("GET", "/approvals", {"workspace_id": "ws"}),
            ("GET", "/export", {"workspace_id": "ws"}),
            ("GET", "/skills", {}),
        ]
        for method, path, params in endpoints:
            if method == "GET":
                resp = client.get(path, params=params)
            else:
                resp = client.post(path, json=params)
            assert resp.status_code == 401, f"{method} {path} should return 401"


def test_auth_docs_protected() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        for path in ("/docs", "/openapi.json"):
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} should return 401 with auth enabled"


def test_auth_docs_accessible_when_disabled() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)
        for path in ("/docs", "/openapi.json"):
            resp = client.get(path)
            assert resp.status_code in (200, 307), f"{path} should be accessible without auth"


def test_auth_protected_endpoints_with_key() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        headers = {"Authorization": "Bearer secret123"}
        endpoints = [
            ("GET", "/traces", {"workspace_id": "ws"}),
            ("GET", "/sessions", {"workspace_id": "ws"}),
            ("GET", "/workspaces", {}),
        ]
        for method, path, params in endpoints:
            if method == "GET":
                resp = client.get(path, params=params, headers=headers)
            else:
                resp = client.post(path, json=params, headers=headers)
            assert resp.status_code != 401, f"{method} {path} should not return 401 with valid key"

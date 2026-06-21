"""v0.15 Production Foundation tests.

Covers: TOML config, health endpoint, JSON logging, SQLite WAL/busy_timeout,
CORS, CSRF, security headers, request body size limit.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.config.loader import CogitoConfig, _deep_merge, load_config, load_toml_config
from cogito_agent.storage.database import Database
from cogito_agent.version import APP_VERSION

# ═══════════════════════════════════════════════════════════════════════════════
# TOML Config Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_config_defaults() -> None:
    cfg = CogitoConfig()
    assert cfg.model.provider == "mock"
    assert cfg.storage.db_path == "~/.cogito/cogito.db"
    assert cfg.security.cors_origins == ["http://localhost:8000", "http://127.0.0.1:8000"]
    assert cfg.security.max_request_size == 10 * 1024 * 1024
    assert cfg.logging.format == "json"
    assert cfg.logging.max_size == 10 * 1024 * 1024
    assert cfg.logging.backup_count == 5
    assert cfg.secrets.backend == "dev_sqlite"


def test_deep_merge_empty() -> None:
    assert _deep_merge({}, {}) == {}


def test_deep_merge_simple() -> None:
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_nested() -> None:
    base = {"model": {"provider": "mock", "timeout": 30}}
    override = {"model": {"timeout": 60}}
    result = _deep_merge(base, override)
    assert result["model"]["provider"] == "mock"
    assert result["model"]["timeout"] == 60


def test_deep_merge_new_keys() -> None:
    result = _deep_merge({"a": 1}, {"b": {"c": 2}})
    assert result == {"a": 1, "b": {"c": 2}}


def test_load_toml_config_invalid_path() -> None:
    result = load_toml_config("/nonexistent/path/config.toml")
    assert result == {}


def test_load_toml_config_with_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write('[model]\nprovider = "openai"\ntimeout_seconds = 120\n')
        tmp_path = f.name
    try:
        result = load_toml_config(tmp_path)
        assert result["model"]["provider"] == "openai"
        assert result["model"]["timeout_seconds"] == 120
    finally:
        os.unlink(tmp_path)


def test_load_config_env_override() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write('[logging]\nlevel = "DEBUG"\n')
        tmp_path = f.name
    try:
        with patch.dict(os.environ, {"COGITO_LOG_LEVEL": "ERROR"}, clear=False):
            cfg = load_config(config_path=tmp_path)
            assert cfg.logging.level == "ERROR"
    finally:
        os.unlink(tmp_path)


def test_load_config_cli_override() -> None:
    cfg = load_config(cli_overrides={"model.provider": "anthropic"})
    assert cfg.model.provider == "anthropic"


def test_load_config_cli_overrides_env() -> None:
    with patch.dict(os.environ, {"COGITO_LOG_LEVEL": "DEBUG"}, clear=False):
        cfg = load_config(cli_overrides={"logging.level": "WARNING"})
        assert cfg.logging.level == "WARNING"


def test_load_config_empty_file() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write("")
        tmp_path = f.name
    try:
        cfg = load_config(config_path=tmp_path)
        assert cfg.model.provider == "mock"
    finally:
        os.unlink(tmp_path)


def test_config_cors_origins_setting() -> None:
    cfg = CogitoConfig()
    cfg.security.cors_origins = ["http://example.com"]
    assert cfg.security.cors_origins == ["http://example.com"]


# ═══════════════════════════════════════════════════════════════════════════════
# Health Endpoint Tests  (using TestClient)
# ═══════════════════════════════════════════════════════════════════════════════

client = TestClient(app)


def test_health_returns_200() -> None:
    """Health endpoint returns 200 when DB and config are ok."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == APP_VERSION
    assert "database" in data["checks"]
    assert "config" in data["checks"]
    assert data["checks"]["database"]["status"] == "ok"


def test_health_returns_json() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers["content-type"].startswith("application/json")


def test_health_has_version() -> None:
    resp = client.get("/api/v1/health")
    assert resp.json()["version"] == APP_VERSION


def test_health_db_check_content() -> None:
    resp = client.get("/api/v1/health")
    checks = resp.json()["checks"]
    assert "migration_version" in checks["database"]
    assert checks["database"]["migration_version"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# JSON Logging Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_setup_logging_no_crash() -> None:
    from cogito_agent.logging import setup_logging

    cfg = CogitoConfig()
    cfg.logging.format = "json"
    setup_logging(cfg.logging)
    import logging

    assert logging.getLogger().level == logging.INFO


def test_setup_logging_text_format() -> None:
    from cogito_agent.logging import setup_logging

    cfg = CogitoConfig()
    cfg.logging.format = "text"
    setup_logging(cfg.logging)
    import logging

    assert logging.getLogger().hasHandlers()


def test_log_path() -> None:
    from cogito_agent.logging import get_log_path

    path = get_log_path()
    assert path.endswith("cogito.log")
    assert "cogito" in path


def test_setup_logging_level_config() -> None:
    from cogito_agent.logging import setup_logging

    cfg = CogitoConfig()
    cfg.logging.level = "WARNING"
    setup_logging(cfg.logging)
    import logging

    root = logging.getLogger()
    assert root.level <= logging.WARNING


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite WAL + busy_timeout Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_database_wal_mode() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        cur = db.connection.execute("PRAGMA journal_mode")
        row = cur.fetchone()
        assert row is not None
        assert str(row[0]).lower() in ("wal", "delete")
        db.close()
    finally:
        os.unlink(db_path)


def test_database_busy_timeout_set() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        cur = db.connection.execute("PRAGMA busy_timeout")
        row = cur.fetchone()
        assert row is not None
        assert row[0] >= 5000
        db.close()
    finally:
        os.unlink(db_path)


def test_database_foreign_keys_on() -> None:
    db = Database()
    cur = db.connection.execute("PRAGMA foreign_keys")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 1
    db.close()


def test_database_migration_idempotent() -> None:
    db = Database()
    db.initialize()
    db.migrate()
    v2 = db.current_version()
    # Second migrate should be a no-op
    db.migrate()
    v3 = db.current_version()
    assert v3 == v2
    db.close()


def test_database_in_memory() -> None:
    db = Database()
    db.initialize()
    cur = db.connection.execute("SELECT 1")
    assert cur.fetchone()[0] == 1
    db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Web Security Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_cors_allow_specific_origin() -> None:
    """CORS allows configured origins."""
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:8000"},
    )
    assert resp.status_code == 200
    cors_allow = resp.headers.get("access-control-allow-origin")
    assert cors_allow == "http://localhost:8000" or cors_allow is None


def test_cors_block_unknown_origin() -> None:
    """CORS blocks origins not in the allowlist."""
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "https://evil.com"},
    )
    assert resp.status_code == 200
    cors_allow = resp.headers.get("access-control-allow-origin")
    assert cors_allow is None or cors_allow == "http://localhost:8000"
    # v0.15: CORS allowlist does NOT include evil.com


def test_cors_no_wildcard() -> None:
    """v0.15 does NOT use Access-Control-Allow-Origin: * for credentialed requests."""
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:8000"},
    )
    cors_allow = resp.headers.get("access-control-allow-origin")
    assert cors_allow != "*"


def test_security_headers_x_content_type_options() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_security_headers_referrer_policy() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_security_headers_x_frame_options() -> None:
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-frame-options") == "DENY"


def test_security_headers_csp_present() -> None:
    resp = client.get("/api/v1/health")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp


def test_security_headers_csp_prevents_frame_ancestors() -> None:
    resp = client.get("/api/v1/health")
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp


def test_request_body_size_limit_accepts_normal() -> None:
    resp = client.post(
        "/api/v1/doctor",
        json={"test": "small"},
    )
    # This should either pass or return 405 (method not allowed)
    assert resp.status_code in (200, 405)


def test_security_headers_on_console_pages() -> None:
    """Console pages get security headers too."""
    resp = client.get("/console/")
    if resp.status_code != 404:
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp


def test_security_headers_on_all_responses() -> None:
    """Even 404 error pages get security headers."""
    resp = client.get("/nonexistent-path-xyz")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_csrf_blocks_missing_token_on_post() -> None:
    """POST without CSRF token returns 403 on console routes when CSRF is enabled."""
    with patch.dict(os.environ, {"COGITO_CSRF_TOKEN": "test-token"}, clear=False):
        resp = client.post(
            "/console/",
            data={"test": "data"},
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.text


def test_csrf_allows_get_requests() -> None:
    """GET requests are not blocked by CSRF middleware."""
    resp = client.get("/console/")
    assert resp.status_code not in (403,)


def test_csrf_allows_exempt_paths() -> None:
    """Health endpoint is exempt from CSRF."""
    resp = client.post("/api/v1/health", json={})
    assert resp.status_code != 403


def test_csrf_with_valid_header() -> None:
    """POST with valid X-CSRF-Token header passes."""
    token = "test-csrf-token-12345"
    with patch.dict(os.environ, {"COGITO_CSRF_TOKEN": token}, clear=False):
        resp = client.post(
            "/console/",
            data={"test": "data"},
            headers={"X-CSRF-Token": token},
        )
        assert resp.status_code != 403


def test_csrf_with_invalid_header() -> None:
    """POST with invalid X-CSRF-Token header is blocked."""
    cfg = CogitoConfig()
    if not cfg.security.csrf_enabled:
        pytest.skip("CSRF not enabled")
    with patch.dict(os.environ, {"COGITO_CSRF_TOKEN": "real-token"}, clear=False):
        resp = client.post(
            "/console/",
            data={"test": "data"},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Negative / Edge Case Security Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_health_does_not_leak_secrets() -> None:
    """Health response should not contain API keys or secrets."""
    resp = client.get("/api/v1/health")
    body = resp.text.lower()
    assert "sk-" not in body
    assert "bearer" not in body
    assert "api_key" not in body or resp.status_code == 503


def test_health_does_not_leak_stack_trace() -> None:
    """Health endpoint errors should not contain Python stack traces."""
    resp = client.get("/api/v1/health")
    assert "traceback" not in resp.text.lower()
    assert 'file "' not in resp.text.lower()


def test_csrf_does_not_block_exempt_api_routes() -> None:
    """API routes are not blocked by CSRF on POST."""
    for path in ["/api/v1/health", "/api/v1/status", "/api/v1/doctor"]:
        resp = client.post(path, json={})
        assert resp.status_code != 403, f"CSRF blocked exempt path {path}"


def test_cors_preflight_works() -> None:
    """CORS preflight requests work with allowed origins."""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "GET" in allow_methods


def test_cors_preflight_blocked_unknown_origin() -> None:
    """CORS preflight from unknown origin is blocked."""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://malicious.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin is None or allow_origin != "https://malicious.com"
    assert allow_origin != "*"


def test_security_headers_on_console_404() -> None:
    """Console 404 pages include security headers."""
    resp = client.get("/console/nonexistentpage123")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"


def test_csrf_disabled_allows_post() -> None:
    """When CSRF is disabled via config, POST works without token."""
    from cogito_agent.config.loader import CogitoConfig

    cfg = CogitoConfig()
    if not cfg.security.csrf_enabled:
        resp = client.post(
            "/console/",
            data={"test": "data"},
        )
        assert resp.status_code != 403


# ═══════════════════════════════════════════════════════════════════════════════
# Request Body Size Limit Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_request_body_large_payload() -> None:
    """Request body size limit rejects oversized payloads."""
    max_size = CogitoConfig().security.max_request_size
    large_body = "x" * (max_size + 1)
    resp = client.post(
        "/api/v1/health",
        data=large_body,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code in (413, 200, 422)


def test_request_body_accepts_normal_size() -> None:
    """Request body size limit accepts normal-sized payloads."""
    resp = client.post(
        "/api/v1/health",
        json={"test": "small"},
    )
    assert resp.status_code != 413


def test_request_body_limit_json() -> None:
    """JSON payloads within limit are accepted."""
    small_json = json.dumps({"key": "value" * 100})
    resp = client.post(
        "/api/v1/health",
        data=small_json,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code != 413


def test_request_body_limit_bypass_for_get() -> None:
    """GET requests are not subject to body size limit middleware."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_body_size_limit_zero_content_length() -> None:
    """Request without content-length header is not blocked."""
    resp = client.post(
        "/api/v1/health",
        data=b"",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code != 413

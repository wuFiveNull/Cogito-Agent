from __future__ import annotations

from cogito_agent.trace.redaction import RedactionHelper


def test_error_response_redacts_bearer_token() -> None:
    r = RedactionHelper()
    message = "Unauthorized: Bearer mysecrettoken123456"
    safe = r.redact(message)
    assert "Bearer [REDACTED]" in safe
    assert "mysecrettoken123456" not in safe


def test_error_response_redacts_api_key() -> None:
    r = RedactionHelper()
    message = "Invalid key: sk-abcdefghijklmnopqrstuvwxyz1234567890"
    safe = r.redact(message)
    assert "[REDACTED_API_KEY]" in safe
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in safe


def test_error_response_redacts_url_credentials() -> None:
    r = RedactionHelper()
    message = "Connection refused to https://admin:secret123@db.internal:5432"
    safe = r.redact(message)
    assert "https://[REDACTED]@" in safe
    assert "admin:secret123" not in safe


def test_error_response_redacts_cookie_header() -> None:
    r = RedactionHelper()
    message = "Header parse error: Cookie: session_id=abc123; Path=/"
    safe = r.redact(message)
    assert "Cookie: [REDACTED]" in safe
    assert "session_id=abc123" not in safe


def test_error_response_redacts_authorization_header() -> None:
    r = RedactionHelper()
    message = "Missing scope for Authorization: Bearer ghp_testtoken"
    safe = r.redact(message)
    assert "Authorization: [REDACTED]" in safe
    assert "ghp_testtoken" not in safe


def test_error_response_does_not_expose_internal_details() -> None:
    r = RedactionHelper()
    message = (
        "Internal error processing request. "
        "Traceback: ... in _call_model: api_key='sk-abcdef1234567890abcdef1234567890'"
    )
    safe = r.redact(message)
    assert "sk-abcdef1234567890abcdef1234567890" not in safe
    assert "[REDACTED_API_KEY]" in safe or "[REDACTED]" in safe


def test_error_response_preserves_safe_error_message() -> None:
    r = RedactionHelper()
    message = "Workspace 'default' not found"
    safe = r.redact(message)
    assert safe == message


def test_error_response_preserves_generic_validation_error() -> None:
    r = RedactionHelper()
    message = "Validation failed: 'session_id' field required"
    safe = r.redact(message)
    assert safe == message


def test_error_response_redacts_query_param_secret() -> None:
    r = RedactionHelper()
    message = "Failed to fetch: https://api.example.com/data?access_token=ghp_abc123def456"
    safe = r.redact(message)
    assert "[REDACTED]" in safe
    assert "ghp_abc123def456" not in safe

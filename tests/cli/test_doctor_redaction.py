from cogito_agent.trace import RedactionHelper


def test_redact_full_bearer_token_replacement() -> None:
    r = RedactionHelper()
    result = r.redact("Bearer ghp_abcdefghijklmnopqrstuvwxyz12345")
    assert "Bearer [REDACTED]" in result
    assert "ghp_abcdefghijklmnopqrstuvwxyz12345" not in result


def test_redact_full_sk_key_replacement() -> None:
    r = RedactionHelper()
    result = r.redact("sk-abcdefghijklmnopqrstuvwxyz1234567890")
    assert "[REDACTED_API_KEY]" in result
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in result


def test_redact_key_value_pattern_replacement() -> None:
    r = RedactionHelper()
    result = r.redact("api_key: 'my-api-key-value-here'")
    assert "[KEY]=[REDACTED]" in result or "[KEY]=[REDACTED]" in result
    assert "my-api-key-value-here" not in result


def test_redact_multiple_secrets_in_single_string() -> None:
    r = RedactionHelper()
    input_str = (
        "URL: https://user:pass@host.com, Header: Authorization: Bearer tok123, Cookie: session=abc"
    )
    result = r.redact(input_str)
    assert "https://[REDACTED]@" in result
    assert "Authorization: [REDACTED]" in result
    assert "Cookie: [REDACTED]" in result
    assert "user:pass" not in result
    assert "tok123" not in result
    assert "session=abc" not in result


def test_secret_not_partially_replaced() -> None:
    r = RedactionHelper()
    input_str = "my_api_key_here = sk-longapikey12345678901234567890"
    result = r.redact(input_str)
    assert "[REDACTED_API_KEY]" in result or "[REDACTED]" in result
    assert "sk-longapikey12345678901234567890" not in result


def test_no_false_positive_on_safe_strings() -> None:
    r = RedactionHelper()
    safe = (
        "Connection OK. 0 sessions active. Workspace 'default' found. "
        "No pending approvals. Memory usage: 128 MB."
    )
    result = r.redact(safe)
    assert result == safe


def test_no_false_positive_on_short_secret_like_strings() -> None:
    r = RedactionHelper()
    safe = "sk is a prefix, not a secret"
    result = r.redact(safe)
    assert result == safe


def test_no_false_positive_on_url_without_credentials() -> None:
    r = RedactionHelper()
    safe = "https://example.com/api/v1/health"
    result = r.redact(safe)
    assert result == safe


def test_no_false_positive_on_plain_json() -> None:
    r = RedactionHelper()
    safe = '{"status": "ok", "version": "0.2.0"}'
    result = r.redact(safe)
    assert result == safe

from cogito_agent.trace import RedactionHelper
from cogito_agent.trace.redaction import PatternRule


def test_redact_bearer_token() -> None:
    r = RedactionHelper()
    result = r.redact("Bearer mysecrettoken123")
    assert "Bearer [REDACTED]" in result
    assert "mysecrettoken123" not in result


def test_redact_sk_api_key() -> None:
    r = RedactionHelper()
    result = r.redact("My key is sk-abc123def456ghi789jklmnopqrstuv")
    assert "[REDACTED_API_KEY]" in result
    assert "sk-abc123def456ghi789jklmnopqrstuv" not in result


def test_redact_authorization_header() -> None:
    r = RedactionHelper()
    result = r.redact("Authorization: Basic dXNlcjpwYXNz")
    assert "Authorization: [REDACTED]" in result
    assert "Basic dXNlcjpwYXNz" not in result


def test_redact_cookie_header() -> None:
    r = RedactionHelper()
    result = r.redact("Cookie: sessionid=abc123; csrftoken=xyz789")
    assert "Cookie: [REDACTED]" in result
    assert "sessionid=abc123" not in result


def test_redact_url_credentials() -> None:
    r = RedactionHelper()
    result = r.redact("https://user:password@example.com/path")
    assert "https://[REDACTED]@" in result
    assert "user:password" not in result


def test_redact_query_param_api_key() -> None:
    r = RedactionHelper()
    result = r.redact("https://api.example.com/data?api_key=sk-abc123def456")
    assert "[REDACTED]" in result
    assert "sk-abc123def456" not in result


def test_redact_query_param_token() -> None:
    r = RedactionHelper()
    result = r.redact("https://api.example.com/data?token=ghp_abc123def456")
    assert "[REDACTED]" in result
    assert "ghp_abc123def456" not in result


def test_redact_session_token() -> None:
    r = RedactionHelper()
    result = r.redact("session_token=abc123def456ghi789jkl")
    assert "[REDACTED]" in result


def test_redact_auth_token_value() -> None:
    r = RedactionHelper()
    result = r.redact("auth-token: some-secret-value-here")
    assert "[REDACTED]" in result
    assert "some-secret-value-here" not in result


def test_custom_rule_addition() -> None:
    r = RedactionHelper(rules=[])
    r.add_rule(PatternRule(r"\d{4}-\d{4}-\d{4}-\d{4}", "[CARD]"))
    result = r.redact("Card: 1234-5678-9012-3456")
    assert "[CARD]" in result
    assert "1234-5678-9012-3456" not in result


def test_false_positive_guard() -> None:
    r = RedactionHelper()
    result = r.redact("This is normal text without any secrets or tokens")
    assert result == "This is normal text without any secrets or tokens"


def test_short_string_not_redacted() -> None:
    r = RedactionHelper()
    result = r.redact("sk-abc")
    assert "sk-abc" in result

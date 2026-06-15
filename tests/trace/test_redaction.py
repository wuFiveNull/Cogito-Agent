from cogito_agent.trace import RedactionHelper


def test_redact_api_key() -> None:
    r = RedactionHelper()
    result = r.redact("My key is sk-abc123def456ghi789jklmnopqrstuv")
    assert "[REDACTED_API_KEY]" in result
    assert "sk-abc123def456ghi789jklmnopqrstuv" not in result


def test_redact_bearer_token() -> None:
    r = RedactionHelper()
    result = r.redact("Authorization: Bearer mysecrettoken123")
    assert "[REDACTED]" in result
    assert "mysecrettoken123" not in result


def test_redact_apikey_header() -> None:
    r = RedactionHelper()
    result = r.redact("X-API-Key: my-secret-key-here")
    assert "[REDACTED]" in result


def test_no_false_positive() -> None:
    r = RedactionHelper()
    result = r.redact("This is normal text without secrets")
    assert result == "This is normal text without secrets"


def test_custom_rules() -> None:
    from cogito_agent.trace.redaction import PatternRule

    r = RedactionHelper(rules=[PatternRule(r"\d{4}-\d{4}-\d{4}", "[CARD]")])
    result = r.redact("Card: 1234-5678-9012")
    assert "[CARD]" in result

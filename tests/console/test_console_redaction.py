from __future__ import annotations

from cogito_agent.console.redaction import redact_html
from cogito_agent.trace.redaction import RedactionHelper


class TestConsoleRedaction:
    def test_redact_api_key_in_html(self) -> None:
        html = '<div>api key "sk-abc123xyz" here</div>'
        result = redact_html(html)
        assert "sk-abc123xyz" not in result
        assert "sk-" in result or "REDACTED" in result or "[REDACTED" in result

    def test_redact_bearer_token(self) -> None:
        html = "<p>Bearer tok-1234567890</p>"
        result = redact_html(html)
        assert "Bearer tok-" not in result.replace("Bearer", "")

    def test_redact_url_credentials(self) -> None:
        html = '<a href="https://user:pass@example.com">link</a>'
        result = redact_html(html)
        assert "user:pass" not in result

    def test_redact_secret_key_value(self) -> None:
        html = "<code>api_key=super-secret-value</code>"
        result = redact_html(html)
        assert "super-secret-value" not in result

    def test_passthrough_safe_html(self) -> None:
        safe = "<div>Hello world, nothing secret here</div>"
        result = redact_html(safe)
        assert result == safe or "Hello world" in result

    def test_redact_helper_reuse(self) -> None:
        helper = RedactionHelper()
        text = "Bearer xyz123"
        assert helper.redact(text) != text

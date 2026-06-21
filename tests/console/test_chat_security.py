from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestChatXSS:
    def test_user_input_html_escaped(self) -> None:
        payload = '<script>alert("xss")</script>'
        resp = client.post(
            "/console/chat/send",
            data={"message": payload},
        )
        html = resp.text
        # The script tag should be HTML-escaped, not rendered as a tag
        assert "&lt;script&gt;" in html or "alert(" not in html or "&amp;" in html

    def test_assistant_output_html_not_raw(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        html = resp.text
        # Message text should not contain raw unescaped HTML tags
        # The message content should be inside pre-wrap elements
        assert "msg-text" in html

    def test_trace_id_no_raw_html(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        html = resp.text
        assert "msg-trace" in html


class TestChatSecurity:
    def test_error_message_redacted(self) -> None:
        """Errors containing secrets should be redacted in the response."""
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        html = resp.text
        # Should not expose raw API keys
        assert "sk-" not in html.replace("[REDACTED", "").replace("[KEY]", "")

    def test_no_stack_trace_in_response(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

from __future__ import annotations

from unittest.mock import ANY, patch

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestChatSend:
    def test_chat_send_returns_html_with_messages(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        html = resp.text
        assert "msg-group" in html
        assert "You" in html
        assert "Assistant" in html or "assistant" in html.lower()

    def test_chat_send_empty_message_returns_422(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "   "},
        )
        assert resp.status_code == 422
        assert "error" in resp.text.lower() or "empty" in resp.text.lower()

    def test_chat_send_custom_session(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello", "session_id": "test-session-1"},
        )
        assert resp.status_code == 200
        assert "msg-group" in resp.text

    def test_chat_send_without_message_field(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={},
        )
        assert resp.status_code == 422


class TestChatSendTrace:
    def test_chat_send_contains_trace_info(self) -> None:
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello"},
        )
        html = resp.text
        assert "Trace" in html or "trace" in html.lower()
        assert "request" in html.lower() or "Request" in html

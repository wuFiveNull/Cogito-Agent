from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestChatStreamEndpoint:
    def test_chat_stream_returns_sse(self) -> None:
        resp = client.post(
            "/console/chat/stream",
            data={"message": "hello"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    def test_chat_stream_sse_has_correct_events(self) -> None:
        resp = client.post(
            "/console/chat/stream",
            data={"message": "hello"},
        )
        body = resp.text
        assert "event:" in body
        assert "data:" in body

    def test_chat_stream_metadata_event(self) -> None:
        resp = client.post(
            "/console/chat/stream",
            data={"message": "hello"},
        )
        # Should contain at least a metadata or delta event
        assert (
            "event: metadata" in resp.text
            or "event: delta" in resp.text
            or "event: final" in resp.text
        )

    def test_chat_stream_empty_message(self) -> None:
        resp = client.post(
            "/console/chat/stream",
            data={"message": "   "},
        )
        # Empty message with streaming should still work (no error)
        assert resp.status_code == 200

    def test_chat_stream_custom_session(self) -> None:
        resp = client.post(
            "/console/chat/stream",
            data={"message": "ping", "session_id": "stream-test-session"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestConsoleChatPage:
    def test_chat_page_returns_200(self) -> None:
        resp = client.get("/console/chat")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_chat_page_has_input_and_send(self) -> None:
        resp = client.get("/console/chat")
        html = resp.text
        assert "chat-input" in html
        assert "Send" in html
        assert "textarea" in html

    def test_chat_page_has_chat_messages_container(self) -> None:
        resp = client.get("/console/chat")
        assert "chat-messages" in resp.text
        assert "chat-form" in resp.text


class TestConsoleDashboard:
    def test_dashboard_returns_200(self) -> None:
        resp = client.get("/console/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_title(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "Dashboard" in html
        assert "Cogito" in html
        assert "version" in html.lower()

    def test_dashboard_shows_stat_cards(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "Memories" in html
        assert "Pending Approvals" in html
        assert "Traces (24h)" in html


class TestConsolePlaceholders:
    @pytest.mark.parametrize("page", ["autonomy", "config", "doctor"])
    def test_placeholder_pages(self, page: str) -> None:
        resp = client.get(f"/console/{page}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Coming soon" in resp.text

    def test_unknown_page_returns_404(self) -> None:
        resp = client.get("/console/foobar")
        assert resp.status_code == 404
        assert "Not Found" in resp.text

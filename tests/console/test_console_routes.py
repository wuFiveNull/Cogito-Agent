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


class TestConsolePages:
    @pytest.mark.parametrize(
        "page,expected",
        [
            ("config", "Configuration"),
            ("doctor", "Doctor"),
        ],
    )
    def test_real_pages(self, page: str, expected: str) -> None:
        resp = client.get(f"/console/{page}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert expected in resp.text
        assert "Coming soon" not in resp.text

    def test_unknown_page_returns_404(self) -> None:
        resp = client.get("/console/foobar")
        assert resp.status_code == 404
        assert "Not Found" in resp.text


class TestDoctorAPI:
    def test_doctor_api_returns_json(self) -> None:
        resp = client.get("/api/v1/doctor")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "warning", "error")
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert "limitations" in data

    def test_doctor_api_has_checks(self) -> None:
        resp = client.get("/api/v1/doctor")
        data = resp.json()
        assert len(data["checks"]) > 0
        sections = {c["section"] for c in data["checks"] if "section" in c}
        assert "core" in sections

    def test_doctor_api_live_returns_501(self) -> None:
        resp = client.get("/api/v1/doctor?live=1")
        assert resp.status_code == 501
        data = resp.json()
        assert data["status"] == "error"

    def test_doctor_api_no_leak(self) -> None:
        resp = client.get("/api/v1/doctor")
        data = resp.text
        assert "sk-" not in data  # no secret leakage
        assert "Bearer " not in data

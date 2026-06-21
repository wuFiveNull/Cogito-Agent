from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestTraceAuditIntegration:
    def test_chat_message_template_uses_detail_link(self) -> None:
        """Chat template should use /console/traces/{trace_id} not query param."""
        import uuid

        # Render the template directly to verify the link pattern
        tid = str(uuid.uuid4())
        from pathlib import Path

        from fastapi.templating import Jinja2Templates

        here = Path("src/cogito_agent/console").resolve()
        templates = Jinja2Templates(directory=str(here / "templates"))
        from unittest.mock import MagicMock

        request = MagicMock()
        html = templates.TemplateResponse(
            request,
            "console/components/chat_message.html",
            {
                "request": request,
                "user_message": "hi",
                "assistant_message": "hello",
                "trace_id": tid,
                "request_id": "req-123",
                "state": "completed",
                "session_id": "sess-1",
                "workspace_id": "default",
            },
        ).body.decode()
        assert f"/console/traces/{tid}" in html
        assert "/console/traces?trace_id=" not in html

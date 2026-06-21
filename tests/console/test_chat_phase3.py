from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.console.markdown import render_safe_markdown
from cogito_agent.console.services import ChatWorkspaceService
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SpanKind
from cogito_agent.storage import Database, MessageRepository, SessionRepository
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.trace import Tracer


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    WorkspaceRepository(database).create("default", "default")
    return database


def test_safe_markdown_renders_allowlisted_content() -> None:
    rendered = render_safe_markdown(
        "## Result\n\n**done** and `code`\n\n- one\n- two\n\n```\n<x>\n```"
    )

    assert "<h4>Result</h4>" in rendered
    assert "<strong>done</strong>" in rendered
    assert "<code>code</code>" in rendered
    assert "<ul>" in rendered
    assert "&lt;x&gt;" in rendered


def test_safe_markdown_blocks_xss_unsafe_links_and_secrets() -> None:
    rendered = render_safe_markdown(
        "<script>alert(1)</script> [bad](javascript:alert(1)) Bearer sk-secret-value"
    )

    assert "<script>" not in rendered
    assert "javascript:" not in rendered
    assert "sk-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_chat_service_paginates_sessions(db: Database) -> None:
    repo = SessionRepository(db)
    for index in range(5):
        repo.create(f"session-{index}", "default", f"Session {index}")

    page = ChatWorkspaceService(db).list_sessions("default", page=2, page_size=2)

    assert len(page["items"]) == 2
    assert page["page"] == 2
    assert page["has_more"] is True


def test_chat_service_paginates_latest_messages(db: Database) -> None:
    SessionRepository(db).create("session", "default", "Session")
    messages = MessageRepository(db)
    for index in range(45):
        messages.create(f"message-{index}", "default", "session", "user", f"message {index}")

    page = ChatWorkspaceService(db).get_messages("default", "session", page=1, page_size=40)

    assert page is not None
    assert len(page["messages"]) == 40
    assert page["has_older"] is True
    assert page["messages"][0]["content"] == "message 5"


def test_rename_and_branch_are_audited(db: Database) -> None:
    sessions = SessionRepository(db)
    sessions.create("source", "default", "Original")
    MessageRepository(db).create("message", "default", "source", "user", "branch context")
    service = ChatWorkspaceService(db)

    renamed = service.rename_session("default", "source", "  Renamed   session ")
    branch = service.branch_session("default", "source")

    assert renamed is not None and renamed["title"] == "Renamed session"
    assert branch is not None and str(branch["title"]).endswith("— branch")
    copied = MessageRepository(db).list_by_session(str(branch["id"]), "default")
    assert [message["content"] for message in copied] == ["branch context"]
    actions = {
        row["action"]
        for row in db.connection.execute(
            "SELECT action FROM audit_logs WHERE resource = 'session'"
        ).fetchall()
    }
    assert {"session_renamed", "session_branched"} <= actions


def test_turn_inspector_is_workspace_scoped_and_redacted(db: Database) -> None:
    tracer = Tracer(db)
    trace = tracer.create_trace("default", "event")
    span = tracer.create_span(trace.id, "model.route", SpanKind.model)
    tracer.log_model_call(
        trace.id,
        span.id,
        provider="deepseek",
        model="flash",
        error="Bearer sk-inspector-secret",
    )
    tracer.end_span(span)
    tracer.end_trace(trace)

    service = ChatWorkspaceService(db)
    inspector = service.get_turn_inspector("default", trace.id)

    assert inspector is not None
    assert inspector["model_calls"][0]["provider"] == "deepseek"
    assert "sk-inspector-secret" not in json.dumps(inspector)
    assert service.get_turn_inspector("other-workspace", trace.id) is None


def test_runtime_persists_trace_reference_on_assistant_message(db: Database) -> None:
    SessionRepository(db).create("session", "default", "Session")
    event = RuntimeEvent(
        workspace_id="default",
        session_id="session",
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hello"},
    )

    result = RuntimeKernel(db).process(event)
    assistant = MessageRepository(db).list_by_session("session", "default")[-1]

    assert json.loads(str(assistant["metadata_json"]))["trace_id"] == result.trace_id


def test_chat_page_exposes_workspace_and_inspector(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    api_module = sys.modules["cogito_agent.api.app"]
    api_module._db = db
    api_module._kernel = RuntimeKernel(db)
    monkeypatch.setattr(
        "cogito_agent.cli.config_manager.build_model_adapter_from_config",
        lambda: None,
    )

    response = TestClient(app).get("/console/chat")

    assert response.status_code == 200
    assert 'class="chat-workspace"' in response.text
    assert 'id="turn-inspector"' in response.text
    assert 'id="stop-turn"' in response.text

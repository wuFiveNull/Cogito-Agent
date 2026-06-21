from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app, get_db
from cogito_agent.storage.repositories import MessageRepository, SessionRepository

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the shared database singleton before each test."""
    import sys

    api_mod = sys.modules["cogito_agent.api.app"]
    api_mod._db = None
    api_mod._kernel = None
    monkeypatch.setattr(
        "cogito_agent.cli.config_manager.build_model_adapter_from_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "cogito_agent.config.loader.build_multimodel_adapter",
        lambda _config: None,
    )
    _ensure_default_workspace()
    yield


CONSOLE_WORKSPACE_ID = "default"


def _shared_db():
    return get_db()


def _ensure_default_workspace() -> None:
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = _shared_db()
    ws_repo = WorkspaceRepository(db)
    if ws_repo.get_by_id(CONSOLE_WORKSPACE_ID) is None:
        ws_repo.create(CONSOLE_WORKSPACE_ID, CONSOLE_WORKSPACE_ID)


def _cleanup_session(session_id: str) -> None:
    db = _shared_db()
    repo = SessionRepository(db)
    repo.hard_delete(session_id, CONSOLE_WORKSPACE_ID)


class TestChatSessionsList:
    def test_list_sessions_returns_html(self) -> None:
        resp = client.get("/console/chat/sessions")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestChatSessionsCreate:
    def test_create_session_returns_session_item(self) -> None:
        resp = client.post("/console/chat/sessions")
        assert resp.status_code == 200
        html = resp.text
        assert "session-item" in html
        assert "New Chat" in html or "session-id" in html

    def test_create_session_persists_to_db(self) -> None:
        db = _shared_db()
        repo = SessionRepository(db)
        count_before = len(repo.list_by_workspace(CONSOLE_WORKSPACE_ID))

        resp = client.post("/console/chat/sessions")
        assert resp.status_code == 200

        count_after = len(repo.list_by_workspace(CONSOLE_WORKSPACE_ID))
        assert count_after == count_before + 1

    def test_new_session_in_list_after_create(self) -> None:
        resp_list = client.get("/console/chat/sessions")
        assert resp_list.status_code == 200

    def test_create_session_with_custom_id(self) -> None:
        sess_id = f"test-sess-{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/console/chat/send",
            data={"message": "hello", "session_id": sess_id},
        )
        assert resp.status_code == 200

        db = _shared_db()
        db.initialize()
        db.migrate()
        repo = SessionRepository(db)
        sess = repo.get_by_id(sess_id, CONSOLE_WORKSPACE_ID)
        assert sess is not None
        _cleanup_session(sess_id)


class TestChatSessionsGet:
    def test_get_session_returns_messages(self) -> None:
        sess_id = f"test-sess-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "ping", "session_id": sess_id},
        )
        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "message" in html.lower() or "msg-" in html

    def test_get_session_empty_ok(self) -> None:
        _ensure_default_workspace()
        db = _shared_db()
        db.initialize()
        db.migrate()
        repo = SessionRepository(db)
        sess_id = f"empty-{uuid.uuid4().hex[:8]}"
        repo.create(sess_id, CONSOLE_WORKSPACE_ID, "Empty Test")

        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "chat-empty" in html or "Send a message" in html
        _cleanup_session(sess_id)

    def test_get_session_not_found(self) -> None:
        resp = client.get("/console/chat/sessions/nonexistent-session-id")
        assert resp.status_code == 404
        assert "error" in resp.text.lower()

    def test_get_session_shows_history(self) -> None:
        sess_id = f"hist-{uuid.uuid4().hex[:8]}"
        for msg_text in ["first", "second"]:
            client.post(
                "/console/chat/send",
                data={"message": msg_text, "session_id": sess_id},
            )
        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "first" in html
        assert "second" in html


class TestChatSessionsArchive:
    def test_archive_session_removes_from_list(self) -> None:
        sess_id = f"arch-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "test", "session_id": sess_id},
        )
        resp = client.post(f"/console/chat/sessions/{sess_id}/archive")
        assert resp.status_code == 200

        db = _shared_db()
        db.initialize()
        db.migrate()
        repo = SessionRepository(db)
        sess = repo.get_by_id(sess_id, CONSOLE_WORKSPACE_ID)
        assert sess is None

    def test_archive_nonexistent_session(self) -> None:
        resp = client.post("/console/chat/sessions/no-such-session/archive")
        assert resp.status_code == 404

    def test_archive_session_twice_returns_404(self) -> None:
        sess_id = f"arch2-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "test", "session_id": sess_id},
        )
        resp1 = client.post(f"/console/chat/sessions/{sess_id}/archive")
        assert resp1.status_code == 200
        resp2 = client.post(f"/console/chat/sessions/{sess_id}/archive")
        assert resp2.status_code == 404


class TestChatSessionsDelete:
    def test_delete_session_removes_messages(self) -> None:
        sess_id = f"del-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "delete me", "session_id": sess_id},
        )
        resp = client.post(f"/console/chat/sessions/{sess_id}/delete")
        assert resp.status_code == 200

        db = _shared_db()
        db.initialize()
        db.migrate()
        sess_repo = SessionRepository(db)
        msg_repo = MessageRepository(db)
        assert sess_repo.get_by_id(sess_id, CONSOLE_WORKSPACE_ID) is None
        msgs = msg_repo.list_by_session(sess_id, CONSOLE_WORKSPACE_ID)
        assert len(msgs) == 0

    def test_delete_nonexistent_session(self) -> None:
        resp = client.post("/console/chat/sessions/no-such-session/delete")
        assert resp.status_code == 404


class TestChatPageWithSessions:
    def test_chat_page_has_session_data(self) -> None:
        resp = client.get("/console/chat")
        assert resp.status_code == 200
        html = resp.text
        assert "session-list" in html or "Sessions" in html

    def test_chat_page_loads_messages_via_hx_get(self) -> None:
        resp = client.get("/console/chat")
        assert resp.status_code == 200


class TestChatSessionSecurity:
    def test_sk_redacted_in_session_title(self) -> None:
        sess_id = f"sec-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "my api key is sk-abc123xyz456def789ghi", "session_id": sess_id},
        )
        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "sk-" not in html

    def test_bearer_token_redacted_in_message(self) -> None:
        sess_id = f"sec2-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "Bearer my-secret-token-value", "session_id": sess_id},
        )
        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "Bearer my-secret-token-value" not in html

    def test_script_tag_escaped(self) -> None:
        sess_id = f"sec3-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "<script>alert('xss')</script>", "session_id": sess_id},
        )
        resp = client.get(f"/console/chat/sessions/{sess_id}")
        assert resp.status_code == 200
        html = resp.text
        # User-provided content must be HTML-escaped
        assert "&lt;script&gt;alert" in html
        # Raw user-controlled script tag should NOT appear
        assert "<script>alert('xss')</script>" not in html

    def test_auth_protects_session_routes(self) -> None:
        from cogito_agent.storage.repositories import WorkspaceRepository

        db = _shared_db()
        db.initialize()
        db.migrate()
        ws_repo = WorkspaceRepository(db)
        if ws_repo.get_by_id(CONSOLE_WORKSPACE_ID) is None:
            ws_repo.create(CONSOLE_WORKSPACE_ID, CONSOLE_WORKSPACE_ID)
        repo = SessionRepository(db)
        sess_id = f"auth-{uuid.uuid4().hex[:8]}"
        repo.create(sess_id, CONSOLE_WORKSPACE_ID, "Auth Test")

        import os

        os.environ["COGITO_API_KEY"] = "test-auth-key"
        try:
            resp_no_auth = client.get(f"/console/chat/sessions/{sess_id}")
            assert resp_no_auth.status_code == 401

            resp_wrong = client.get(
                f"/console/chat/sessions/{sess_id}",
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp_wrong.status_code == 401

            resp_valid = client.get(
                f"/console/chat/sessions/{sess_id}",
                headers={"Authorization": "Bearer test-auth-key"},
            )
            assert resp_valid.status_code == 200
        finally:
            os.environ.pop("COGITO_API_KEY", None)

    def test_no_stack_trace_in_session_errors(self) -> None:
        resp = client.get("/console/chat/sessions/nonexistent-session-id")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_no_stack_trace_in_archive_errors(self) -> None:
        resp = client.post("/console/chat/sessions/nonexistent/archive")
        html = resp.text
        assert "Traceback" not in html

    def test_no_stack_trace_in_delete_errors(self) -> None:
        resp = client.post("/console/chat/sessions/nonexistent/delete")
        html = resp.text
        assert "Traceback" not in html


class TestChatSessionAudit:
    def test_session_create_writes_audit_log(self) -> None:
        db = _shared_db()
        db.initialize()
        db.migrate()
        count_before = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_created'",
        ).fetchone()["c"]

        client.post("/console/chat/sessions")

        count_after = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_created'",
        ).fetchone()["c"]
        assert count_after > count_before

    def test_session_archive_writes_audit_log(self) -> None:
        sess_id = f"aud-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "test", "session_id": sess_id},
        )

        db = _shared_db()
        db.initialize()
        db.migrate()
        count_before = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_archived'",
        ).fetchone()["c"]

        client.post(f"/console/chat/sessions/{sess_id}/archive")

        count_after = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_archived'",
        ).fetchone()["c"]
        assert count_after > count_before

    def test_session_delete_writes_audit_log(self) -> None:
        sess_id = f"aud2-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "test", "session_id": sess_id},
        )

        db = _shared_db()
        db.initialize()
        db.migrate()
        count_before = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_deleted'",
        ).fetchone()["c"]

        client.post(f"/console/chat/sessions/{sess_id}/delete")

        count_after = db.connection.execute(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'session_deleted'",
        ).fetchone()["c"]
        assert count_after > count_before


class TestChatSessionMessages:
    def test_message_persistence_user_and_assistant(self) -> None:
        sess_id = f"persist-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "hello world", "session_id": sess_id},
        )

        db = _shared_db()
        db.initialize()
        db.migrate()
        msg_repo = MessageRepository(db)
        msgs = msg_repo.list_by_session(sess_id, CONSOLE_WORKSPACE_ID)
        assert len(msgs) >= 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_session_title_from_first_message(self) -> None:
        sess_id = f"title-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "What is the meaning of life?", "session_id": sess_id},
        )

        db = _shared_db()
        db.initialize()
        db.migrate()
        repo = SessionRepository(db)
        sess = repo.get_by_id(sess_id, CONSOLE_WORKSPACE_ID)
        assert sess is not None
        title = str(sess.get("title", ""))
        assert len(title) > 0

    def test_session_list_shows_message_count(self) -> None:
        sess_id = f"count-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "msg1", "session_id": sess_id},
        )

        resp = client.get("/console/chat/sessions")
        assert resp.status_code == 200
        html = resp.text
        assert "msg" in html.lower()

    def test_switch_sessions_preserves_messages(self) -> None:
        sess_a = f"switch-a-{uuid.uuid4().hex[:8]}"
        sess_b = f"switch-b-{uuid.uuid4().hex[:8]}"
        client.post(
            "/console/chat/send",
            data={"message": "message for A", "session_id": sess_a},
        )
        client.post(
            "/console/chat/send",
            data={"message": "message for B", "session_id": sess_b},
        )

        resp_a = client.get(f"/console/chat/sessions/{sess_a}")
        assert "message for A" in resp_a.text
        assert "message for B" not in resp_a.text

        resp_b = client.get(f"/console/chat/sessions/{sess_b}")
        assert "message for B" in resp_b.text
        assert "message for A" not in resp_b.text


class TestChatSessionsListAuth:
    def test_list_sessions_requires_auth(self) -> None:
        import os

        os.environ["COGITO_API_KEY"] = "test-list-auth"
        try:
            resp_no = client.get("/console/chat/sessions")
            assert resp_no.status_code == 401

            resp_ok = client.get(
                "/console/chat/sessions",
                headers={"Authorization": "Bearer test-list-auth"},
            )
            assert resp_ok.status_code == 200
        finally:
            os.environ.pop("COGITO_API_KEY", None)

    def test_create_session_requires_auth(self) -> None:
        import os

        os.environ["COGITO_API_KEY"] = "test-create-auth"
        try:
            resp_no = client.post("/console/chat/sessions")
            assert resp_no.status_code == 401

            resp_ok = client.post(
                "/console/chat/sessions",
                headers={"Authorization": "Bearer test-create-auth"},
            )
            assert resp_ok.status_code == 200
        finally:
            os.environ.pop("COGITO_API_KEY", None)

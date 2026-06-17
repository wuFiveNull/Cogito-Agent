from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


def _ensure_decision() -> str:
    from cogito_agent.api.app import get_db
    from cogito_agent.autonomy import DecisionStore

    db = get_db()
    dstore = DecisionStore(db)
    import uuid
    did = str(uuid.uuid4())
    dstore.save_decision(
        decision_id=did,
        event_id=str(uuid.uuid4()),
        workspace_id="default",
        user_id="test-user",
        action="push",
        reason_code="test_reason",
        reason="This is a test decision for console",
        cost_score=0.5,
        priority_score=1.0,
        dedup_hit=False,
        quiet_hours_hit=False,
        quota_hit=False,
        requires_approval=False,
    )
    return did


def _ensure_outbox(decision_id: str) -> str:
    from cogito_agent.api.app import get_db
    from cogito_agent.autonomy import Outbox

    db = get_db()
    obox = Outbox(db)
    return obox.enqueue(
        event_id="test-event",
        decision_id=decision_id,
        title="Test Outbox Message",
        body="This is a test outbox body",
        workspace_id="default",
        trace_id="test-trace",
    )


def _ensure_feedback(decision_id: str) -> None:
    from cogito_agent.api.app import get_db
    from cogito_agent.autonomy import FeedbackStore
    from cogito_agent.governance import AuditLogger

    db = get_db()
    fb = FeedbackStore(db, audit_logger=AuditLogger(db))
    fb.record_feedback(
        decision_id=decision_id,
        event_id="test-event",
        value="useful",
        comment="Great decision!",
        workspace_id="default",
    )


class TestAutonomyDashboard:
    def test_dashboard_returns_200(self) -> None:
        resp = client.get("/console/autonomy")
        assert resp.status_code == 200

    def test_empty_db_no_crash(self) -> None:
        resp = client.get("/console/autonomy")
        assert resp.status_code == 200

    def test_shows_stat_cards(self) -> None:
        did = _ensure_decision()
        resp = client.get("/console/autonomy")
        assert "Total Decisions" in resp.text
        assert "Push" in resp.text
        assert "Outbox Pending" in resp.text

    def test_shows_quick_links(self) -> None:
        resp = client.get("/console/autonomy")
        assert "/console/autonomy/decisions" in resp.text
        assert "/console/autonomy/outbox" in resp.text
        assert "/console/autonomy/feedback" in resp.text


class TestAutonomyDecisions:
    def test_decisions_list_returns_200(self) -> None:
        resp = client.get("/console/autonomy/decisions")
        assert resp.status_code == 200

    def test_empty_decisions_no_crash(self) -> None:
        resp = client.get("/console/autonomy/decisions")
        assert resp.status_code == 200

    def test_shows_decision_in_list(self) -> None:
        did = _ensure_decision()
        resp = client.get("/console/autonomy/decisions")
        assert did in resp.text
        assert "push" in resp.text.lower()
        assert "test_reason" in resp.text

    def test_action_filter(self) -> None:
        resp = client.get("/console/autonomy/decisions?action=skip")
        assert resp.status_code == 200

    def test_search_filter(self) -> None:
        resp = client.get("/console/autonomy/decisions?q=test_reason")
        assert resp.status_code == 200

    def test_time_range_filter(self) -> None:
        resp = client.get("/console/autonomy/decisions?time_range=24h")
        assert resp.status_code == 200


class TestAutonomyDecisionDetail:
    def test_detail_found(self) -> None:
        did = _ensure_decision()
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert resp.status_code == 200
        assert did in resp.text

    def test_detail_not_found(self) -> None:
        resp = client.get("/console/autonomy/decisions/nonexistent-id")
        assert resp.status_code == 404

    def test_detail_shows_trace_link(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import DecisionStore
        import uuid

        db = get_db()
        dstore = DecisionStore(db)
        did = str(uuid.uuid4())
        dstore.save_decision(
            decision_id=did, event_id=str(uuid.uuid4()),
            workspace_id="default", user_id="u",
            action="push", reason_code="rc", reason="r",
            cost_score=0.5, priority_score=1.0,
            dedup_hit=False, quiet_hours_hit=False, quota_hit=False,
            requires_approval=False, trace_id="trace-abc-123",
        )
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert resp.status_code == 200
        assert "/console/traces/trace-abc-123" in resp.text

    def test_detail_shows_related_outbox(self) -> None:
        did = _ensure_decision()
        _ensure_outbox(did)
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert "Outbox" in resp.text or "outbox" in resp.text

    def test_detail_shows_feedback_form(self) -> None:
        did = _ensure_decision()
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert "feedback" in resp.text.lower()
        assert 'method="post"' in resp.text

    def test_no_stack_trace_on_404(self) -> None:
        resp = client.get("/console/autonomy/decisions/nonexistent")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_xss_escape(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import DecisionStore
        import uuid

        db = get_db()
        dstore = DecisionStore(db)
        did = str(uuid.uuid4())
        dstore.save_decision(
            decision_id=did, event_id=str(uuid.uuid4()),
            workspace_id="default", user_id="<script>alert('xss')</script>",
            action="push", reason_code="<script>", reason="<b>bold</b>",
            cost_score=0.5, priority_score=1.0,
            dedup_hit=False, quiet_hours_hit=False, quota_hit=False,
            requires_approval=False,
        )
        resp = client.get(f"/console/autonomy/decisions/{did}")
        html = resp.text
        assert "<script>" not in html
        assert "<b>" not in html


class TestAutonomyFeedback:
    def test_feedback_page_returns_200(self) -> None:
        resp = client.get("/console/autonomy/feedback")
        assert resp.status_code == 200

    def test_feedback_page_empty_no_crash(self) -> None:
        resp = client.get("/console/autonomy/feedback")
        assert resp.status_code == 200

    def test_feedback_page_shows_entries(self) -> None:
        did = _ensure_decision()
        _ensure_feedback(did)
        resp = client.get("/console/autonomy/feedback")
        assert "useful" in resp.text.lower()

    def test_feedback_value_filter(self) -> None:
        resp = client.get("/console/autonomy/feedback?value=useful")
        assert resp.status_code == 200

    def test_feedback_decision_id_filter(self) -> None:
        did = _ensure_decision()
        _ensure_feedback(did)
        resp = client.get(f"/console/autonomy/feedback?decision_id={did}")
        assert resp.status_code == 200

    def test_post_feedback_useful(self) -> None:
        did = _ensure_decision()
        resp = client.post(
            f"/console/autonomy/decisions/{did}/feedback",
            data={"value": "useful", "comment": "Test comment"},
            follow_redirects=False,
        )
        assert resp.status_code in (303, 302)

    def test_post_feedback_too_many(self) -> None:
        did = _ensure_decision()
        resp = client.post(
            f"/console/autonomy/decisions/{did}/feedback",
            data={"value": "too_many", "comment": ""},
            follow_redirects=False,
        )
        assert resp.status_code in (303, 302)

    def test_post_feedback_wrong_time(self) -> None:
        did = _ensure_decision()
        resp = client.post(
            f"/console/autonomy/decisions/{did}/feedback",
            data={"value": "wrong_time"},
            follow_redirects=False,
        )
        assert resp.status_code in (303, 302)

    def test_post_feedback_invalid_value(self) -> None:
        did = _ensure_decision()
        resp = client.post(
            f"/console/autonomy/decisions/{did}/feedback",
            data={"value": "invalid_value"},
        )
        assert resp.status_code == 422

    def test_post_feedback_nonexistent_decision(self) -> None:
        resp = client.post(
            "/console/autonomy/decisions/nonexistent-id/feedback",
            data={"value": "useful"},
        )
        assert resp.status_code == 404

    def test_feedback_xss_escape(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import DecisionStore, FeedbackStore
        from cogito_agent.governance import AuditLogger
        import uuid

        db = get_db()
        dstore = DecisionStore(db)
        did = str(uuid.uuid4())
        dstore.save_decision(
            decision_id=did, event_id=str(uuid.uuid4()),
            workspace_id="default", user_id="u",
            action="push", reason_code="rc", reason="r",
            cost_score=0.5, priority_score=1.0,
            dedup_hit=False, quiet_hours_hit=False, quota_hit=False,
            requires_approval=False,
        )
        fb = FeedbackStore(db, audit_logger=AuditLogger(db))
        fb.record_feedback(
            decision_id=did, event_id="e",
            value="useful", comment="<script>alert('xss')</script>",
            workspace_id="default",
        )
        resp = client.get("/console/autonomy/feedback")
        assert "<script>" not in resp.text


class TestAutonomyOutbox:
    def test_outbox_list_returns_200(self) -> None:
        resp = client.get("/console/autonomy/outbox")
        assert resp.status_code == 200

    def test_empty_outbox_no_crash(self) -> None:
        resp = client.get("/console/autonomy/outbox")
        assert resp.status_code == 200

    def test_shows_outbox_message(self) -> None:
        did = _ensure_decision()
        mid = _ensure_outbox(did)
        resp = client.get("/console/autonomy/outbox")
        assert mid in resp.text

    def test_status_filter(self) -> None:
        resp = client.get("/console/autonomy/outbox?status=pending")
        assert resp.status_code == 200

    def test_search_filter(self) -> None:
        resp = client.get("/console/autonomy/outbox?q=Test+Outbox")
        assert resp.status_code == 200

    def test_time_range_filter(self) -> None:
        resp = client.get("/console/autonomy/outbox?time_range=24h")
        assert resp.status_code == 200


class TestAutonomyOutboxDetail:
    def test_detail_found(self) -> None:
        did = _ensure_decision()
        mid = _ensure_outbox(did)
        resp = client.get(f"/console/autonomy/outbox/{mid}")
        assert resp.status_code == 200
        assert mid in resp.text

    def test_detail_not_found(self) -> None:
        resp = client.get("/console/autonomy/outbox/nonexistent-id")
        assert resp.status_code == 404

    def test_detail_shows_decision_link(self) -> None:
        did = _ensure_decision()
        mid = _ensure_outbox(did)
        resp = client.get(f"/console/autonomy/outbox/{mid}")
        assert f"/console/autonomy/decisions/{did}" in resp.text

    def test_detail_shows_trace_link(self) -> None:
        did = _ensure_decision()
        mid = _ensure_outbox(did)
        resp = client.get(f"/console/autonomy/outbox/{mid}")
        assert "/console/traces/test-trace" in resp.text

    def test_no_stack_trace_on_404(self) -> None:
        resp = client.get("/console/autonomy/outbox/nonexistent")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_outbox_xss_escape(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import Outbox
        import uuid

        db = get_db()
        obox = Outbox(db)
        did = str(uuid.uuid4())
        mid = obox.enqueue(
            event_id="e", decision_id=did,
            title="<script>alert('xss')</script>",
            body="<b>bold</b>",
            workspace_id="default",
        )
        resp = client.get(f"/console/autonomy/outbox/{mid}")
        assert "<script>" not in resp.text
        assert "<b>" not in resp.text


class TestAutonomySecurity:
    def test_outbox_body_redacted_bearer(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import Outbox
        import uuid

        db = get_db()
        obox = Outbox(db)
        did = str(uuid.uuid4())
        mid = obox.enqueue(
            event_id="e", decision_id=did,
            title="Test",
            body="Token: sk-my-secret-api-key-12345",
            workspace_id="default",
        )
        resp = client.get(f"/console/autonomy/outbox/{mid}")
        html = resp.text
        assert "sk-my-secret-api-key-12345" not in html

    def test_decision_reason_redacted_api_key(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.autonomy import DecisionStore
        import uuid

        db = get_db()
        dstore = DecisionStore(db)
        did = str(uuid.uuid4())
        dstore.save_decision(
            decision_id=did, event_id=str(uuid.uuid4()),
            workspace_id="default", user_id="u",
            action="push", reason_code="rc",
            reason="Key: sk-test-key-abcdef123456",
            cost_score=0.5, priority_score=1.0,
            dedup_hit=False, quiet_hours_hit=False, quota_hit=False,
            requires_approval=False,
        )
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert "sk-test-key-abcdef123456" not in resp.text

    def test_raw_json_redacted(self) -> None:
        did = _ensure_decision()
        resp = client.get(f"/console/autonomy/decisions/{did}")
        assert "sk-" not in resp.text


class TestAutonomyAuth:
    @pytest.fixture(autouse=True)
    def _save_restore_key(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get("/console/autonomy")
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get(
            "/console/autonomy",
            headers={"Authorization": "Bearer test-autonomy-key"},
        )
        assert resp.status_code == 200

    def test_auth_blocks_decisions_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get("/console/autonomy/decisions")
        assert resp.status_code == 401

    def test_auth_allows_decisions_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get(
            "/console/autonomy/decisions",
            headers={"Authorization": "Bearer test-autonomy-key"},
        )
        assert resp.status_code == 200

    def test_auth_blocks_outbox_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get("/console/autonomy/outbox")
        assert resp.status_code == 401

    def test_auth_blocks_feedback_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-autonomy-key"
        resp = client.get("/console/autonomy/feedback")
        assert resp.status_code == 401

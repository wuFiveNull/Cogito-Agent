from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.shared.trace import SpanKind

client = TestClient(app)


def _ensure_trace() -> str:
    from cogito_agent.api.app import get_db
    from cogito_agent.trace import Tracer

    db = get_db()
    tracer = Tracer(db)
    trace = tracer.create_trace("default", str(uuid.uuid4()), "test-sess")
    span = tracer.create_span(trace.id, "test_span", SpanKind.runtime)
    tracer.end_span(span)
    tracer.end_trace(trace)
    return trace.id


class TestTracesPage:
    def test_traces_page_returns_200(self) -> None:
        resp = client.get("/console/traces")
        assert resp.status_code == 200

    def test_empty_db_no_crash(self) -> None:
        resp = client.get("/console/traces")
        assert resp.status_code == 200

    def test_status_filter_completed(self) -> None:
        resp = client.get("/console/traces?status=completed")
        assert resp.status_code == 200

    def test_status_filter_error(self) -> None:
        resp = client.get("/console/traces?status=error")
        assert resp.status_code == 200

    def test_time_range_filter(self) -> None:
        resp = client.get("/console/traces?time_range=24h")
        assert resp.status_code == 200

    def test_search_filter(self) -> None:
        resp = client.get("/console/traces?q=test")
        assert resp.status_code == 200

    def test_shows_trace_id_in_list(self) -> None:
        tid = _ensure_trace()
        resp = client.get("/console/traces")
        assert tid in resp.text


class TestTraceDetail:
    def test_detail_not_found(self) -> None:
        resp = client.get("/console/traces/nonexistent-trace-id")
        assert resp.status_code == 404

    def test_detail_returns_200(self) -> None:
        tid = _ensure_trace()
        resp = client.get(f"/console/traces/{tid}")
        assert resp.status_code == 200
        assert "test_span" in resp.text

    def test_detail_shows_span_tree(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.trace import Tracer

        db = get_db()
        tracer = Tracer(db)
        trace = tracer.create_trace("default", str(uuid.uuid4()), "sess")
        root = tracer.create_span(trace.id, "root", SpanKind.runtime)
        child = tracer.create_span(trace.id, "child", SpanKind.model, parent_span_id=root.id)
        tracer.end_span(root)
        tracer.end_span(child)
        tracer.end_trace(trace)

        resp = client.get(f"/console/traces/{trace.id}")
        assert "root" in resp.text
        assert "child" in resp.text
        assert "trc-tree-root" in resp.text or "trc-tree" in resp.text


class TestTraceSecurity:
    def test_no_stack_trace_on_404(self) -> None:
        resp = client.get("/console/traces/nonexistent")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_trace_xss_escape(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.trace import Tracer

        db = get_db()
        tracer = Tracer(db)
        trace = tracer.create_trace("default", str(uuid.uuid4()), "sess")
        span_name = '<script>alert("xss")</script>'
        tracer.create_span(trace.id, span_name, SpanKind.runtime)
        tracer.end_trace(trace)

        resp = client.get(f"/console/traces/{trace.id}")
        html = resp.text
        # User-controlled span name must be HTML-escaped
        assert "&lt;script&gt;alert" in html or "redacted" in html.lower()
        # Raw user-controlled script tag should NOT appear in the page
        assert '<script>alert("xss")</script>' not in html


class TestTraceAuth:
    @pytest.fixture(autouse=True)
    def _save_restore_key(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-trace-key"
        resp = client.get("/console/traces")
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-trace-key"
        resp = client.get("/console/traces", headers={"Authorization": "Bearer test-trace-key"})
        assert resp.status_code == 200

from __future__ import annotations

from datetime import UTC, datetime

from cogito_agent.shared import Span, SpanKind, Trace
from cogito_agent.storage import Database


class Tracer:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_trace(
        self,
        workspace_id: str,
        root_event_id: str,
        session_id: str | None = None,
    ) -> Trace:
        trace = Trace(
            workspace_id=workspace_id,
            root_event_id=root_event_id,
            session_id=session_id,
        )
        self._db.connection.execute(
            "INSERT INTO traces (id, workspace_id, session_id, root_event_id)"
            " VALUES (?, ?, ?, ?)",
            (trace.id, workspace_id, session_id, root_event_id),
        )
        self._db.connection.commit()
        return trace

    def create_span(
        self,
        trace_id: str,
        name: str,
        kind: SpanKind,
        parent_span_id: str | None = None,
    ) -> Span:
        span = Span(
            trace_id=trace_id,
            name=name,
            kind=kind,
            parent_span_id=parent_span_id,
        )
        self._db.connection.execute(
            "INSERT INTO spans"
            " (id, trace_id, parent_span_id, name, kind)"
            " VALUES (?, ?, ?, ?, ?)",
            (span.id, trace_id, parent_span_id, name, kind.value),
        )
        self._db.connection.commit()
        return span

    def end_span(self, span: Span, status: str = "completed") -> Span:
        span.status = status
        span.ended_at = datetime.now(UTC)
        self._db.connection.execute(
            "UPDATE spans SET status = ?, ended_at = ? WHERE id = ?",
            (status, span.ended_at.isoformat(), span.id),
        )
        self._db.connection.commit()
        return span

    def end_trace(self, trace: Trace, status: str = "completed") -> Trace:
        trace.status = status
        trace.ended_at = datetime.now(UTC)
        self._db.connection.execute(
            "UPDATE traces SET status = ?, ended_at = ? WHERE id = ?",
            (status, trace.ended_at.isoformat(), trace.id),
        )
        self._db.connection.commit()
        return trace

    def log_tool_call(
        self,
        trace_id: str,
        span_id: str,
        capability_name: str,
        input_summary: str = "",
        decision: str = "",
        status: str = "",
        output_summary: str = "",
        latency_ms: int = 0,
        error: str | None = None,
        redactions: list[str] | None = None,
    ) -> None:
        if redactions:
            for token in redactions:
                input_summary = input_summary.replace(token, "[REDACTED]")
                output_summary = output_summary.replace(token, "[REDACTED]")
        self._db.connection.execute(
            "INSERT INTO tool_calls"
            " (trace_id, span_id, capability_name, input_summary,"
            " decision, status, output_summary, latency_ms, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id, span_id, capability_name, input_summary,
                decision, status, output_summary, latency_ms, error,
            ),
        )
        self._db.connection.commit()

    def log_model_call(
        self,
        trace_id: str,
        span_id: str,
        provider: str = "",
        model: str = "",
        input_token_count: int = 0,
        output_token_count: int = 0,
        prompt_summary: str = "",
        response_summary: str = "",
        latency_ms: int = 0,
        stop_reason: str = "",
        error: str | None = None,
        redactions: list[str] | None = None,
    ) -> None:
        if redactions:
            for token in redactions:
                prompt_summary = prompt_summary.replace(token, "[REDACTED]")
                response_summary = response_summary.replace(token, "[REDACTED]")
        self._db.connection.execute(
            "INSERT INTO model_calls"
            " (trace_id, span_id, provider, model,"
            " input_token_count, output_token_count,"
            " prompt_summary, response_summary,"
            " latency_ms, stop_reason, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id, span_id, provider, model,
                input_token_count, output_token_count,
                prompt_summary, response_summary,
                latency_ms, stop_reason, error,
            ),
        )
        self._db.connection.commit()

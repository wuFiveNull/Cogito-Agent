from __future__ import annotations

from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


def _setup(db: Database) -> tuple[Tracer, str, str]:
    tracer = Tracer(db)
    trace = tracer.create_trace("ws-1", "evt-1")
    span = tracer.create_span(trace.id, "model", SpanKind.model)
    return tracer, trace.id, span.id


def test_log_model_call_redacts_prompt_summary(db: Database) -> None:
    tracer, trace_id, span_id = _setup(db)
    tracer.log_model_call(
        trace_id=trace_id,
        span_id=span_id,
        prompt_summary="User asked: my Bearer token123",
        response_summary="safe response",
        redactions=["Bearer token123"],
    )
    cur = db.connection.execute(
        "SELECT prompt_summary, response_summary FROM model_calls WHERE trace_id = ?",
        (trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert "[REDACTED]" in row["prompt_summary"]
    assert "Bearer token123" not in row["prompt_summary"]
    assert row["response_summary"] == "safe response"


def test_log_model_call_redacts_response_summary(db: Database) -> None:
    tracer, trace_id, span_id = _setup(db)
    tracer.log_model_call(
        trace_id=trace_id,
        span_id=span_id,
        prompt_summary="safe prompt",
        response_summary="My API key is sk-abc123def456ghi789jklmnopqrstuv",
        redactions=["sk-abc123def456ghi789jklmnopqrstuv"],
    )
    cur = db.connection.execute(
        "SELECT prompt_summary, response_summary FROM model_calls WHERE trace_id = ?",
        (trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["prompt_summary"] == "safe prompt"
    assert "[REDACTED]" in row["response_summary"]
    assert "sk-abc123def456ghi789jklmnopqrstuv" not in row["response_summary"]


def test_log_model_call_empty_redactions_list(db: Database) -> None:
    tracer, trace_id, span_id = _setup(db)
    tracer.log_model_call(
        trace_id=trace_id,
        span_id=span_id,
        prompt_summary="prompt with secret",
        response_summary="response with secret",
        redactions=[],
    )
    cur = db.connection.execute(
        "SELECT prompt_summary, response_summary FROM model_calls WHERE trace_id = ?",
        (trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["prompt_summary"] == "prompt with secret"
    assert row["response_summary"] == "response with secret"


def test_log_model_call_none_redactions(db: Database) -> None:
    tracer, trace_id, span_id = _setup(db)
    tracer.log_model_call(
        trace_id=trace_id,
        span_id=span_id,
        prompt_summary="prompt with secret",
        response_summary="response with secret",
        redactions=None,
    )
    cur = db.connection.execute(
        "SELECT prompt_summary, response_summary FROM model_calls WHERE trace_id = ?",
        (trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["prompt_summary"] == "prompt with secret"
    assert row["response_summary"] == "response with secret"


def test_log_model_call_redacts_multiple_tokens(db: Database) -> None:
    tracer, trace_id, span_id = _setup(db)
    tracer.log_model_call(
        trace_id=trace_id,
        span_id=span_id,
        prompt_summary="token1 and token2 here",
        response_summary="also token1 and token2",
        redactions=["token1", "token2"],
    )
    cur = db.connection.execute(
        "SELECT prompt_summary, response_summary FROM model_calls WHERE trace_id = ?",
        (trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["prompt_summary"] == "[REDACTED] and [REDACTED] here"
    assert row["response_summary"] == "also [REDACTED] and [REDACTED]"

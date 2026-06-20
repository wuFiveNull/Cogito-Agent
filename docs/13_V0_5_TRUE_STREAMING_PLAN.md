# v0.5 True Per-Token Streaming — Dogfood Validated Candidate

## Status

- **Current commit:** aeefd78
- **Status:** v0.5 true streaming dogfood validated candidate, **not released**.
- **No GitHub tag or release.**

## Implemented Capabilities

### Core Streaming (`RuntimeKernel.process_stream()`)

- Full-turn streaming via `process_stream()` generator yielding `StreamEvent` objects.
- SSE protocol: `event:` + `data:` lines per [StreamEvent spec](../src/cogito_agent/shared/stream_events.py).
- Event types: `metadata`, `delta`, `final`, `error`, `approval_required`, `tool_call_started`, `tool_call_completed`.

### SSE Event Format

**metadata** (single combined event):
```json
{
  "trace_id": "uuid",
  "session_id": "uuid",
  "workspace_id": "str",
  "channel": "api_stream",
  "request_id": "uuid"
}
```

**delta** (one per token when streaming):
```json
{"delta": "partial token text"}
```

**final**:
```json
{
  "response": "full assembled response",
  "trace_id": "uuid",
  "state": "completed"
}
```

**error** (unified schema):
```json
{
  "error": {
    "code": "POLICY_DENIED|BUDGET_EXCEEDED|RUNTIME_ERROR",
    "message": "human-readable",
    "request_id": "uuid",
    "trace_id": "uuid",
    "retryable": false
  }
}
```

**approval_required**:
```json
{
  "approval_id": "uuid",
  "trace_id": "uuid",
  "summary": "safe summary"
}
```

**tool_call_started / tool_call_completed**:
```json
// tool_call_started
{"tool_count": 1}
// tool_call_completed
{"tool_results": [{"tool": "name", "summary": "..."}]}
```

### RuntimeKernel `process_stream` behavior

1. Creates Tracer trace and span.
2. Yields `metadata` event with trace_id, session_id, workspace_id, channel, request_id.
3. Loads session, builds context, checks budget and model policy.
4. Calls `_stream_generate_reply()` which uses `StreamGenerator`:
   - If `model_adapter` is `None`: yields echo text as single delta.
   - If `adapter.supports_streaming` is `True`: yields per-token deltas from `adapter.stream_chat()`.
   - If `adapter.supports_streaming` is `False`/absent: calls `adapter.chat()`, yields full response as single delta.
5. Dispatches tool intents if present in the model response (after streaming).
6. On `ApprovalRequiredError`: yields `approval_required` event, stops.
7. On `BudgetError`/`PolicyDeniedError`/`Exception`: yields `error` event with unified schema.
8. Yields `final` event with full response, trace_id, state.
9. Ends trace and span.
10. Persists message to DB, extracts memory candidates, writes audit log.

### ModelAdapter Streaming Protocol

```python
class ModelAdapter(Protocol):
    supports_streaming: bool = False
    def chat(self, messages, **kwargs) -> ModelResponse: ...
    def stream_chat(self, messages, **kwargs) -> Iterator[str]: ...
```

- `supports_streaming`: set to `True` on the adapter instance.
- `stream_chat()`: yields individual token strings.
- `StreamGenerator`: wrapper that consumes `stream_chat()` or falls back to `chat()`.
  - After iteration, `StreamGenerator.response` holds the full `ModelResponse`.

### Fallback Behavior

| Condition | Behavior |
|-----------|----------|
| No adapter (`None`) | Echo mode: single delta "You said: {message}" |
| `supports_streaming=False` | `chat()` returns full response → single delta |
| `supports_streaming=True` | `stream_chat()` yields per-token deltas |
| Tool intents in streaming mode | Dispatched after all deltas emitted |
| Approval required | `approval_required` event, no further execution |

### Redaction

- Applied at the API layer (`chat_stream` endpoint in `app.py`).
- Delta events: `sev.data["delta"]` redacted before yielding.
- Error events: `error["message"]` redacted.
- Approval events: `summary` redacted.
- Final events: `response` redacted.
- Rules: Bearer tokens, `sk-` API keys, Authorization/Cookie headers, URL credentials, and custom env-based secrets.

### Trace/Replay/Audit

- Each streaming turn writes a trace with span type `process_stream_turn`.
- Model calls (including streaming) are logged via `Tracer.log_model_call()`.
- Tool calls are logged via `Tracer.log_tool_call()` with redactions.
- Audit log written on completion, approval_required, and errors.
- `cogito traces list/show` and `cogito replay show` work with streaming traces.
- `cogito audit list` shows streaming turns.

### Auth / Rate Limit / Error Schema

- `AuthMiddleware`: Bearer token via `COGITO_API_KEY`. Returns 401 on missing/wrong key.
- `RateLimitMiddleware`: per-IP throttling via `COGITO_RATE_LIMIT_ENABLED`, `COGITO_RATE_LIMIT_PER_MINUTE`.
- Global exception handler: catches unhandled exceptions → 500 JSON.
- `RequestValidationError` handler: structured 422 JSON.
- `RequestIDMiddleware`: sets `X-Request-ID` header.
- `CORSMiddleware`: allow all origins for local dev.
- Error schema: `{"error": {"code", "message", "request_id", "trace_id", "retryable"}}`.

## Tests and Quality Status

- **631 tests passing** (pytest clean)
- **ruff clean** (ruff check src/)
- **mypy clean** (65 source files)
- New in v0.5:
  - `tests/models/mock_model.py` — MockModel adapter for multi-delta testing
  - `tests/runtime/test_process_stream.py` — 8 tests for process_stream events
  - `tests/api/test_stream_governance.py` — 2 tests for approval/policy in streaming
  - `tests/api/test_stream_redaction.py` — 5 tests for per-delta redaction
  - Existing: 13 streaming-related tests from v0.4

## Dogfood Validation Results (v0.5.1)

Run against live API server via subprocess with curl-like HTTP requests.

| Test | Result |
|------|--------|
| `/chat` returns 200 with output + state=completed | PASS |
| `/chat/stream` returns 200 with SSE events | PASS |
| `event: metadata` present (combined: trace_id + session_id + workspace_id + channel + request_id) | PASS |
| `event: delta` present | PASS |
| `event: final` present with state=completed | PASS |
| 3+ SSE events (metadata → delta → final) | PASS |
| All SSE data is valid JSON | PASS |
| trace_id present in metadata/final | PASS |
| request_id present in metadata | PASS |
| No `X-Experimental` header | PASS |
| Trace exists for streaming turn | PASS |
| Traces list API returns 200 | PASS |
| Missing text → 422 with error code, no Python traceback | PASS |
| `api_key=sk-...` secret not in SSE body | PASS |
| Redaction marker present in SSE body | PASS |
| Auth: no auth header → 401 | PASS |
| Auth: wrong Bearer token → 401 | PASS |
| Auth: correct Bearer token → 200 with SSE | PASS |

**28/28 checks passed, 0 failures.**

## Known Limitations

1. **Streaming tool calls**: `stream_chat()` only yields content deltas. Tool intent detection happens after streaming completes. No tool-interrupt during streaming.
2. **Bearer token across deltas**: A "Bearer <secret>" sequence spread across two tokens is not redacted (each token redacted independently).
3. **No async scheduler**: `cogito daemon run` is a blocking sync loop.
4. **No encrypted secret store**: API keys are in-memory plaintext.
5. **No Web UI / TUI**, no Telegram/Feishu channels, no multi-agent workspace, no plugin runtime.
6. **MockModel**: the test adapter does not produce realistic streaming output (word-split, not token-split). Suitable for event validation only.

The limitations above describe the v0.5 implementation and are retained as historical
release context. Several were addressed in later releases.

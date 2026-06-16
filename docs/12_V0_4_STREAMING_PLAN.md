# 12 V0.4.0 Streaming Runtime Integration

> **Status**: Complete — /chat/stream now uses RuntimeKernel.
> **Not released. No GitHub tag or release.**

## Baseline

- **Base commit**: `6839589`
- **Current commit**: (pending dogfood commit)
- **Package**: cogito-agent 0.3.0-dev

## Epic A: /chat/stream RuntimeKernel Integration — Complete

### Changes Made

1. **`src/cogito_agent/api/app.py`** — `/chat/stream` rewritten:
   - Removed `COGITO_ENABLE_EXPERIMENTAL` gate (no longer required)
   - Removed `provider` field from `ChatStreamRequest` (uses kernel's model config)
   - Removed `X-Experimental: bypasses RuntimeKernel` header
   - Now creates `RuntimeEvent` with `source=EventSource.api` and `channel=api_stream`
   - Calls `kernel.process()` — same pipeline as `/chat`
   - Outputs SSE events: `metadata`, `final`, `approval_required`, `error`
   - All output redacted via `RedactionHelper`
   - All errors use unified error schema
   - Returns `trace_id` in metadata/final events

2. **`src/cogito_agent/shared/state.py`** — State machine fix:
   - Terminal states (`completed`, `failed`, `denied`, `cancelled`, `budget_exceeded`) can now transition back to `received`
   - Allows kernel reuse across multiple turn cycles

3. **`src/cogito_agent/runtime/kernel.py`** — Kernel reuse fix:
   - `process()` resets state machine from terminal states before starting a new turn

### SSE Event Format

```
event: metadata
data: {"request_id": "..."}

event: metadata
data: {"trace_id": "...", "session_id": "..."}

event: final
data: {"response": "...", "trace_id": "...", "state": "completed"}

event: approval_required
data: { "approval_id": "...", "summary": "..." }

event: error
data: {"error": {"code": "...", "message": "...", "request_id": "...", "trace_id": "...", "retryable": false}}
```

### What Still Bypasses

Nothing — /chat/stream now fully uses RuntimeKernel.

### What Is NOT Done (Known Limitations)

- **Chunked final response, not true token streaming** — `kernel.process()` runs fully before emitting SSE. True per-token streaming would require changes to `RuntimeKernel._generate_reply()` and `ModelAdapter` interface.
- **No `EventType.stream` or streaming state** — State machine has no `streaming` state. This is fine for chunked final response.
- **No `StreamChunk` / `StreamEvent` types** — Streaming types are defined only at the SSE level (in the API layer).
- **Tool dispatch during streaming** — Not supported. Tools are dispatched during kernel execution, output is chunked after completion.

## New Test Files

| File | Tests |
|------|-------|
| `tests/api/test_stream_runtime.py` | 6 — runtime kernel integration, metadata, final, redaction, gate removal |
| `tests/api/test_stream_error_schema.py` | 4 — 404, 422, unified error schema, no secrets |
| `tests/e2e/test_stream_runtime_e2e.py` | 2 — full E2E streaming flow, trace verification |

Total: **12 new tests**

## Test Results

| Suite | Result |
|-------|--------|
| pytest | **615 passed**, 0 failed |
| ruff check src/ | **0 issues** |
| mypy src/ | **0 issues** (64 files) |

## Files Modified

| File | Change |
|------|--------|
| `src/cogito_agent/api/app.py` | Rewrote `/chat/stream` to use RuntimeKernel; removed experimental gate, provider field, bypass header; added SSE events |
| `src/cogito_agent/shared/state.py` | Terminal states can transition to `received` for kernel reuse |
| `src/cogito_agent/runtime/kernel.py` | `process()` resets state machine from terminal states |
| `README.md` | Updated /chat/stream docs to reflect RuntimeKernel integration |
| `AGENTS.md` | Updated /chat/stream status |

## Next Priorities (v0.5)

1. True per-token streaming via `ModelAdapter.stream_chat()` integration in `RuntimeKernel._generate_reply()`
2. Tool dispatch during streaming (interrupt mid-stream for tool calls)
3. Streaming `EventType` and streaming state in state machine
4. Typed `StreamEvent` / `StreamChunk` classes in shared types

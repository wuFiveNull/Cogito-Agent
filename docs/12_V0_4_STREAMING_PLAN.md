# 12 V0.4.0 Streaming Runtime Integration

> **Status**: Complete — /chat/stream now uses RuntimeKernel. Dogfood validation passed.
> **Not released. No GitHub tag or release.**

## Baseline

- **Base commit**: `6839589`
- **Current commit**: (pending dogfood commit — see below)
- **Dogfood validation commit**: (current HEAD, see git log)
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
data: {"approval_id": "...", "trace_id": "...", "summary": "Approval required"}

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
| `tests/api/test_stream_runtime.py` | 7 — runtime kernel integration, metadata, final, approval_required SSE format, redaction, gate removal |
| `tests/api/test_stream_error_schema.py` | 4 — 404, 422, unified error schema, no secrets |
| `tests/e2e/test_stream_runtime_e2e.py` | 2 — full E2E streaming flow, trace verification |

Total: **13 new tests**

## Dogfood Validation

A standalone validation script `scripts/dogfood_v0_4_validate.py` covers 70 checks across Parts 2–6 using FastAPI `TestClient` in-process (no uvicorn needed):

| Part | Checks | Coverage |
|------|--------|----------|
| Part 2: API / Stream Dogfood | 24 | SSE format, metadata, final, X-Request-ID, no X-Experimental, redaction |
| Part 3a: API Auth | 12 | No key / wrong key / correct key, error schema, no token leak |
| Part 3b: Rate Limit | 5 | 429, retryable=true, no traceback |
| Part 3c: Validation Error | 5 | 422, request_id, no traceback |
| Part 4: Trace / Replay | 7 | Traces exist, trace_id match, spans |
| Part 5: Approval Required | 3 | SSE event emitted, approval_id, trace_id |
| Part 6: Redaction | 14 | All pattern rules, /chat/stream, error responses, no raw secrets |

**Result: 70/70 passed.**

## Bugs Fixed During Dogfood

1. **Middleware ordering crash** (`app.py` lines 151–153): `RateLimitMiddleware` ran before `RequestIDMiddleware`, so `request.state.request_id` was undefined when rate‑limit triggered → `AttributeError`. Fixed by reordering middleware so `RequestIDMiddleware` runs first (outermost).

2. **`approval_required` SSE event had empty `{}` data** (`app.py` line 439–443): Missing `approval_id` and `trace_id` fields. Fixed to include `approval_id`, `trace_id`, and a redacted `summary`.

## Test Results

| Suite | Result |
|-------|--------|
| pytest | **616 passed**, 0 failed |
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

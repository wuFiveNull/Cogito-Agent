# 11 V0.3.0 Core Completion

## Baseline

- **Base commit**: `1272449`
- **Current commit**: `ea09a05`
- **Package**: cogito-agent 0.3.0

## Epic A: Memory V2 — Complete

### Completed Capabilities
- CLI: `cogito memory list|search|review|accept|reject|delete|pin|edit|correct|archive|unarchive|unpin|merge|consolidate`
- `MemoryRepository`: create, get_by_id, list_by_workspace, pin, archive, unarchive, unpin, merge, edit_text, correct_text, soft_delete, get_by_id_including_deleted, list_all_by_workspace, backfill_embeddings
- `MemoryEditRepository`: update_text, hard_delete, list_by_type
- `MemoryRetriever`: search (with FTS5 + LIKE fallback), search_with_lineage, search_hybrid, list_recent
- Retrieval rules: pinned boost (2.0x), type priority, confidence weighting, query text match boost, status boost (consolidated 1.2x), archived exclusion by default, deleted exclusion
- `DriftMaintenance`: consolidate_memories, archive_stale_memories
- Lineage tracking via `source_lineage` in search_with_lineage

### Gap Items Filled
- Added tests for `search_with_lineage()` source_lineage, cross-workspace isolation, include_archived=True/False
- Added tests for list_recent ordering, deleted exclusion, archived inclusion, pinned inclusion
- Added tests for force-edit on archived/deleted memories
- Memory edit/correct preserve old versions, write edit log, update FTS, mark embeddings stale, audit log

### Known Limitations
- No vector DB integration (FTS5 only for MVP)
- `MemoryEditRepository.update_text()` does not update FTS/embeddings (CLI uses `MemoryRepository` methods directly which do)

## Epic B: API Runtime Hardening — Complete

### Completed Capabilities
- Unified error schema: `{"error": {"code", "message", "request_id", "trace_id", "retryable"}}`
- `_error_response()` with RedactionHelper redaction on messages
- `RateLimitMiddleware` with in-memory sliding window (configurable via COGITO_RATE_LIMIT_ENABLED/PER_MINUTE)
- `RequestIDMiddleware`: generates X-Request-ID on all responses
- Validation/global exception handlers (422/500)
- CORS middleware
- `/chat/stream` experimental with X-Experimental header

### Gap Items Filled
- Added rate limit tests: disabled default, limit exceeded, window expiry, error schema
- Added error schema tests: VALIDATION_ERROR, NOT_FOUND, INTERNAL_ERROR, UNAUTHORIZED, redaction, X-Request-ID
- Added request metadata tests: X-Request-ID propagation, generation, error response presence
- Added error redaction tests: Bearer, API key, URL creds, Cookie, Authorization in error messages
- `Tracer.log_model_call()` now accepts `redactions` parameter (like log_tool_call)

### Known Limitations
- `/chat/stream` still bypasses RuntimeKernel (governance/trace/audit) — explicitly marked experimental
- Rate limit is in-memory only, not shared across process restarts
- No request body size limits

## Epic C: Autonomy / Daemon V2 — Complete

### Completed Capabilities
- `ProactiveEngine`: run(), run_once(), stop(), daemon state persistence (status, heartbeat, crash marker, graceful shutdown)
- `SchedulerEngine`: schedule, cancel, get_job, list_jobs, tick, get_job_failures, reset_job
- Job execution with trace/span/audit integration, quiet hours check, policy evaluation
- Retry with exponential backoff, interval rescheduling, duplicate execution guard
- `NotificationGate`: quiet hours, dedup (SHA256 hash), daily quota (per-workspace), priority, `try_notify_or_inbox` fallback
- Inbox CRUD: write_inbox, list_inbox, read_inbox_item, mark_inbox_read, clear_inbox
- CLI: `cogito daemon status|stop`, `cogito inbox list|read|mark-read|clear`
- `JobStatus.cancelled` added

### Gap Items Filled
- `cancel()` now sets status to `cancelled` and `enabled=0`
- Bug fix: `_update_state()` in loop.py had mismatched SQL bindings (5 values for 8 placeholders)
- Added daemon state tests: load_status empty, run_once, heartbeat, running state, stop
- Added scheduler persistence tests: cancel → cancelled status, cancelled→excluded from tick, get_job_failures, reset_job
- Added inbox tests: full CRUD, wildcard listing, read marking, trace_id inclusion, priority defaults
- Added notification gate tests: quiet hours, dedup, daily quota, priority, try_notify_or_inbox

### Known Limitations
- No cross-process daemon control (state markers only)
- `failure_count` column not separated from `retry_count` (same column tracks both)
- No `cogito schedule set-quiet-hours` CLI (works via `NotificationGate.set_quiet_hours()` programmatically)

## Epic D: Skill Runtime V2 — Complete

### Completed Capabilities
- Step types: capability, llm, transform, condition, approval
- Condition step: expression evaluation with $input.xxx, $step.xxx._output, `contains` keyword, safe globals
- Approval step: creates `ApprovalRepository` record + audit log entry
- Execution controls: per-step timeout (default 300s), retry (count + delay), budget tracking, failure_policy (stop/skip/rollback), output schema validation
- Governance: permission preflight, policy evaluation, risk-level-based auditing
- CLI: `cogito skill list|show|validate|import|export|run`
- Replay: skill run IDs, step spans, capability calls, approval interruptions, artifacts/lineage in TraceInspector
- Budget enforcement via `_estimate_step_cost()` and `max_budget_cost` check

### Gap Items Filled
- Budget enforcement: `_estimate_step_cost()` method, budget check before each step execution
- Added condition step tests: empty expression, input refs, step refs, contains keyword, false condition, status logging
- Added approval step tests: pending approval record creation, pending_approval status, audit log entry, approval ID output
- Added execution controls tests: timeout, retry, skip, stop, output validation, budget enforcement
- Added skill run/replay tests: run log creation, step logs persistence, status persistence

### Known Limitations
- Approval step does not block/interrupt — creates record but continues execution immediately
- No `cogito approval` CLI subcommand (approvals are resolvable via API)
- `max_budget_cost` uses simple per-step cost estimates (0.002 for LLM, 0.001 for capability), not actual provider costs

## Epic E: Secret Redaction — Complete

### Completed Capabilities
- 9 static redaction patterns: Bearer token, sk-* keys, key/value headers, Authorization, Cookie, URL credentials, query params, session/auth tokens
- Dynamic rules from COGITO_* env vars via EnvSecretProvider
- `SecretProvider` protocol, `EnvSecretProvider`, `KeychainSecretProvider` (stub)
- `RedactionHelper.redact()`, `redact_dict()`, `add_rule()`
- Redaction applied in: trace span attributes, tool call I/O (via redactions param), model call I/O (via redactions param), audit details, export, API error responses, CLI doctor, CLI inbox, replay output

### Gap Items Filled
- `Tracer.log_model_call()` now accepts `redactions` parameter (same as log_tool_call)
- Added SecretProvider tests: EnvSecretProvider.get_secret, KeychainSecretProvider returns None/empty
- Added redact_dict tests: nested dict, list of strings, non-string primitives preservation
- Added model call redaction tests: prompt_summary/response_summary redacted with populated/empty/None redactions
- Added doctor redaction tests: full replacement, multi-secret strings, false positive guards
- Added API error redaction tests: all pattern types redacted in error messages

### Known Limitations
- `KeychainSecretProvider` remains a stub (no OS keychain integration)
- FTS5/retrieval-path memories not redacted at storage (redacted on read in replay only)
- Duplicate `_redact_dict` in `cli/export.py` vs `RedactionHelper.redact_dict()`

## Test Results

| Suite | Result |
|-------|--------|
| pytest | **564 passed**, 0 failed |
| ruff check src/ | **Clean** (30 pre-existing E501/F401 only, none from v0.3 changes) |
| mypy src/ | **Clean** (24 pre-existing type errors only, none from v0.3 changes) |

## Files Modified (code changes)

| File | Change |
|------|--------|
| `src/cogito_agent/autonomy/loop.py:39` | Fixed `_update_state()` SQL binding count (5→8) |
| `src/cogito_agent/autonomy/scheduler.py:92` | `cancel()` sets `status='cancelled'` + enabled=0, returns bool |
| `src/cogito_agent/shared/schedule.py:14` | Added `JobStatus.cancelled` |
| `src/cogito_agent/skill/runner.py:48` | Budget tracking (`_estimate_step_cost`, total_cost, max_budget_cost check) |
| `src/cogito_agent/trace/tracer.py:103` | `log_model_call()` accepts `redactions: list[str] \| None = None` |

## New Test Files (25 files, 144 new tests)

| Epic | Test File | Tests |
|------|-----------|-------|
| A | `tests/memory/test_search_lineage.py` | 7 |
| A | `tests/memory/test_list_review.py` | 5 |
| A | `tests/memory/test_memory_force.py` | 3 |
| B | `tests/api/test_error_schema.py` | 6 |
| B | `tests/api/test_rate_limit.py` | 5 |
| B | `tests/api/test_request_metadata.py` | 4 |
| B | `tests/api/test_error_redaction.py` | 9 |
| C | `tests/autonomy/test_daemon_state.py` | 5 |
| C | `tests/autonomy/test_scheduler_persistence.py` | 10 |
| C | `tests/autonomy/test_inbox.py` | 14 |
| C | `tests/autonomy/test_notification_gate.py` | 15 |
| D | `tests/skill/test_skill_condition_step.py` | 6 |
| D | `tests/skill/test_skill_approval_step.py` | 4 |
| D | `tests/skill/test_skill_execution_controls.py` | 7 |
| D | `tests/skill/test_skill_cli.py` | 3 |
| D | `tests/skill/test_skill_replay.py` | 4 |
| E | `tests/security/test_redaction.py` | 12 |
| E | `tests/trace/test_secret_redaction.py` | 11 |
| E | `tests/export/test_secret_redaction.py` | 5 |
| E | `tests/cli/test_doctor_redaction.py` | 9 |

## New CLI Commands

None added (all CLI commands existed from first round).

## Database Schema Changes

- `scheduled_jobs.status` now supports `'cancelled'` value (no schema DDL change — just enum expansion)

## Next Priorities (v0.4)

1. Approval step blocking/resume — make skill runner wait for approval resolution
2. `cogito approval list|resolve` CLI subcommand
3. OS keychain integration for `KeychainSecretProvider`
4. `/chat/stream` full RuntimeKernel integration (remove experimental bypass)
5. Vector DB integration for semantic memory search
6. Cross-process daemon control

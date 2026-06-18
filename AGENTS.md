# Repository Guidelines

## State of the Repo

v0.1.0-alpha released.
v0.2.0-alpha released.
v0.3.0-dev not released.
v0.4.0-dev not released.
v0.5.0-dev not released.
v0.6.2-dev (keychain secrets + provider config hardening, not released).
v0.7.0-rc1 (Autonomy Plane MVP release candidate):
- AutonomyEvent with AutonomySourceType (scheduler/drift/webhook/memory/manual/system), PriorityLevel (low/normal/high/urgent), deterministic dedup_key (SHA256)
- normalize_from_dict() / normalize_manual() normalizer
- NotificationGate with rule-based evaluate(): quiet hours, daily/hourly quota, dedup window, deterministic cost score, governance check
- NotificationDecision rich object with action (push/skip/defer/require_approval), reason_code, cost_score
- DecisionStore for notification_decisions table
- Outbox for outbox_messages table (local SQLite queue, NOT real push)
- FeedbackStore with FeedbackValue enum, audit logging
- ProactiveLoop with per-step trace spans (event_received, gate.evaluate, decision.persist, outbox.push, audit.*)
- CLI: `cogito autonomy emit|decisions|outbox|feedback`
- Default policy rule for notification.send (allow_with_audit)
- migration v6 for new tables
- SpanKind.autonomous for autonomy trace spans
- Config keys: autonomy.enabled, quiet_hours.*, notification.*, dedup.*, feedback.*
- docs/16_V0_7_AUTONOMY_NOTIFICATION_GATE_PLAN.md updated

v0.8.0 (Console MVP Phases 1–8, released 2026-06-17):
- **Phase 1 — Foundation**: Console module, Dashboard, Status API, 8 placeholder pages, base layout, auth, redaction, static files, packaging
- **Phase 2 — Chat MVP**: Interactive chat at `/console/chat` with:
  - Message area with user/assistant bubbles
  - Input form with htmx non‑streaming send (`POST /console/chat/send`)
  - SSE streaming endpoint (`POST /console/chat/stream`)
  - Trace ID, request ID, state metadata after each turn
  - HTML escape + redaction on all dynamic content
  - Error banners (redacted, no stack traces)
  - AuthMiddleware integration (401 without valid key)
  - Console‑default session (`console-default`), auto‑created workspace
  - 802 tests passing, ruff clean, mypy clean (82 source files)
- **Phase 3 — Memory Review MVP**: Memory management page at `/console/memory` with:
  - List page with stats (total/pending/active/archived/stale), filter bar (status/search), tabs (All/Candidates/Memories)
  - Detail page with full content, metadata, edit form, action buttons
  - Accept/reject candidates (`POST /console/memory/candidates/{id}/accept|reject|edit`)
  - Edit/archive/delete memories (`POST /console/memory/{id}/edit|archive|delete`)
  - All mutations write audit logs with redacted details
  - Shared `utils.py` with `menu_items()` to avoid circular imports
  - 30 new tests, 831 tests passing, ruff clean, mypy clean (84 source files)
- **Phase 4 — Approval Queue MVP**: Approval management page at `/console/approval` with:
  - List page with stats (total/pending/approved/rejected), filter bar (status/search)
  - Detail page with full metadata, approve/reject forms
  - Approve/reject via `ApprovalRepository.resolve()` (idempotent)
  - Double-process detection with clear error messages
  - All mutations write audit logs with redacted details
  - Reuses `utils.py` for shared menu items
  - 29 new tests, 859 tests passing, ruff clean, mypy clean (85 source files)
- **Phase 5 — Trace & Audit MVP**: Trace and Audit management pages at `/console/traces` and `/console/audit` with:
  - Trace list with status/time/search filters, span counts, durations
  - Trace detail with span tree (parent/child hierarchy via `parent_span_id`), model/tool calls, related audit events, redacted raw JSON
  - Audit list with actor/operation/search/time filters, trace_id links
  - Audit detail with full metadata and redacted details
  - Chat trace link now points to real trace detail (`/console/traces/{trace_id}`)
  - Span tree built from `parent_span_id` with expandable/collapsible nodes
  - All content redacted + HTML escaped; AuthMiddleware protects all routes
  - Shared modules: `trace_views.py`, `audit_views.py` keep router.py clean
  - 29 new tests, 886 tests passing, ruff clean, mypy clean (87 source files)
- **Phase 6 — Autonomy Console MVP**: Autonomy management pages at `/console/autonomy` with:
  - Autonomy dashboard with stat cards (decisions total/24h, push/skip/defer/require_approval counts, outbox pending/sent/failed, feedback counts)
  - Quick links to decisions, outbox, feedback, traces, audit
  - Decisions list with action/reason_code/search/time_range filters, stat cards, decision_id/event_id/reason/trace_id display
  - Decision detail with full metadata, trace_id link, related outbox messages, related feedback, feedback submission form, redacted raw JSON
  - Feedback submission (`POST /console/autonomy/decisions/{id}/feedback`) with value validation (FeedbackValue enum), audit logging, decision existence check
  - Outbox list with status/search/time_range filters, stat cards, decision_id link
  - Outbox detail with title/body/status/decision_id/trace_id display, redacted raw JSON
  - Feedback list with value/decision_id/time_range filters, stat cards, decision_id link
  - DecisionStore extended: `list_decisions_filtered()`, `count_by_action()`
  - Outbox extended: `list_messages_filtered()`, `count_by_status()`
  - FeedbackStore extended: `list_feedback()`, `count_by_value()`
  - All content redacted + HTML escaped; AuthMiddleware protects all routes
  - 49 new tests, 935 tests passing, ruff clean, mypy clean (88 source files)
- **Phase 7 — Config Viewer & Doctor Page**: Console config viewer and doctor page at `/console/config` and `/console/doctor` with:
  - Config viewer at `/console/config`: read-only section-grouped config table (Environment, Model Provider, Secrets, Autonomy, Auth & Console), redacted secret values (API keys, Bearer tokens, passwords), all content HTML-escaped
  - Doctor page at `/console/doctor`: system health check with section-grouped results (core, database, provider, secrets, governance, autonomy, console), overall status badge (ok/warning/error), supports `GET /api/v1/doctor` JSON API
  - Doctor checks include: app version, Python/platform, config load, package availability, DB reachability/schema version/table counts, provider registration/model config/secret resolution, secrets backend availability, PolicyEngine/ApprovalRepository/AuditLogger/Tracer availability, recent audit count, recent traces count, autonomy store availability, template availability, static asset availability, htmx presence, auth middleware status, known limitations
  - Doctor live provider check: skipped by default (returns `"skipped"` status), explicit `?live=1` returns 501 (not implemented in console viewer — use `cogito provider test <name> --live` on CLI)
  - All content redacted + HTML escaped; AuthMiddleware protects both routes
  - Shared modules: `config_views.py`, `doctor_views.py` keep router.py clean
  - Redaction: all config values with `secret_ref`, `api_key`, `password`, `bearer`, `token` patterns redacted via `redact_html()`; Doctor check messages also redacted
  - Templates: `config.html` (section-grouped tables), `doctor.html` (overall status badge + section check cards with name/status/message)
  - 938 tests passing, ruff clean, mypy clean (90 source files)
  - New API: `GET /api/v1/doctor` returns JSON with status, checks, limitations; `?live=1` returns 501
- **Phase 8 — Polish & RC Hardening** (released):
  - Nav active state: sidebar highlights current page
  - Dashboard quick links: no more "coming soon" labels
  - CSS polish: UUID wrapping, raw JSON scroll, empty state, responsive improvements, button styles
  - Loading states: global htmx indicator, CSS opacity on active requests
  - Critical bugfix: `traces.html` / `trace_detail.html` had `<!DOCTYPE html>` before `{% extends %}` (Jinja2 error)
  - Security regression: 73 new unified tests for auth (all pages), secret leak (sk-/Bearer/password), stack trace leak
  - 1011 tests passing, ruff clean, mypy clean (90 source files)

v0.9.0-dev (Multi-Session Chat + History Recovery, current):
- Fixed kernel swapped args bug in `_build_context` and `_build_model_messages` (`list_by_session` was called with wrong arg order)
- User messages are now persisted in the DB (previously only assistant responses were saved)
- Auto-title for sessions from first user message (first 80 chars)
- Session sidebar in chat layout with create/list/switch/archive/delete
- History recovery on page refresh (messages loaded from DB on page load)
- Chat session routes:
  - `GET /console/chat/sessions` — list sessions
  - `POST /console/chat/sessions` — create new session
  - `GET /console/chat/sessions/{id}` — get session with messages
  - `POST /console/chat/sessions/{id}/archive` — soft delete (archive)
  - `POST /console/chat/sessions/{id}/delete` — hard delete
- Audit logging for all session mutations (created/archived/deleted)
- Fixed `SessionRepository.hard_delete` to delete spans before traces (FK fix)
- All content redacted + HTML escaped
- AuthMiddleware protects all session routes
- 32 new tests, 1043 tests passing, ruff clean, mypy clean (91 source files)
- docs/18_V0_9_MULTI_SESSION_CHAT_PLAN.md created

v0.10.0-dev (Core Runtime Hardening):
- Hybrid Memory Search: EmbeddingService fallback to MockEmbeddingService (deterministic hash), HybridRetriever with full hybrid scoring (BM25 + semantic + recency + confidence + pinned boost), MemoryRetriever.search() tries hybrid first
- Streaming Tool Interrupt: process_stream() yields tool_call_started/tool_call_completed SSE events with redacted tool results, full governance pipeline
- Multi-round Tool Loop: RuntimeKernel max_tool_rounds parameter (default 3), process()/process_stream() loops model→tools→model up to max rounds, _dispatch_tools skips follow-up if all tools denied
- MockEmbeddingService: deterministic 384-dim hash-based, no external deps
- 32 new test files (hybrid memory 16, streaming tools 8, tool loop 8), 1070 tests passing
- ruff clean, mypy clean (91 source files)
- docs/19_V0_10_CORE_RUNTIME_HARDENING_PLAN.md created

v0.11.0-dev (Autonomy Delivery & Local Production Hardening, current):
- Secret Store Hardening: LocalEncryptedSecretProvider (Fernet), DevSqliteSecretProvider (dev warning), security risk in Doctor page
- DeliveryAdapter: protocol + LocalInboxDeliveryAdapter + ConsoleNotificationAdapter with standardized DeliveryResult
- OutboxDispatcher: exponential backoff (30s-1h), 5 max retries, dead-letter, trace/audit/redaction per attempt, migration v7
- Web Console Inbox: /console/inbox list/detail with retry/dismiss/read/feedback, stat cards, filters
- Backup CLI: cogito backup create [--include-secrets] / restore [--dry-run], cogito export memories|traces, audit logging
- 27 new tests, 1097 tests passing, ruff clean, mypy clean (95 source files)
- docs/20_V0_11_AUTONOMY_DELIVERY_HARDENING_PLAN.md created

## Verification Status

- **1192 tests passing** (`pytest` clean)
- **ruff clean** (`ruff check src/` clean)
- **mypy clean** (`mypy src/` clean, 112 files)

- ✅ Phase 1 (Epics A–B): Runtime full turn pipeline, context engine with budget shares
- ✅ Phase 2 (Epics C–E): Tool dispatch, approval flow, budget enforcement
- ✅ Phase 3 (Epics F–G): Trace/audit integration, policy matrix (call_model/tool/trace_log)
- ✅ Phase 4 (Epics H–J): Candidate extraction, memory ranking, memory versioning, token_count utility
- ✅ Phase 5 (Epic K): Capability safety — path sandboxing, JSON Schema validation, full ToolResult
- ✅ Phase 5 (Epic L): Storage completeness — hard delete, full export, migration system
- ✅ Phase 5 (Epics K–L): Capability safety (path sandboxing, JSON Schema), storage completeness (hard delete, export, migration)
- ✅ Phase 6 (Epics M–P): Skill runtime depth, background security, failure/retry, interrupt/resume
- ✅ Phase 7 (Epics Q–S): Drift maintenance, CLI/API polish, replay
- ✅ Phase 8 (Autonomy Plane MVP): Notification Gate, Decision Log, Outbox, Proactive Loop, Feedback, CLI, trace/audit integration
- ✅ Phase 9 (V0.14 Real Skills + Drift Runtime): 5 real built-in skills (daily_brief, memory_consolidation, task_extraction, trace_review, inbox_digest), DriftRuntime (tick loop, quiet hours, budget, cooldown, pause/resume), DriftMaintenance, Console Drift page, migration v10

## Console Status (v0.8 Phase 1–2)

- ✅ Console module structure (`src/cogito_agent/console/`)
- ✅ Dashboard at `/console/` with stat cards, system info, quick links
- ✅ Status API at `/api/v1/status` with counts, DB health, provider info, secrets info
- ✅ All 8 initial pages now real (chat, memory, approval, traces, audit, autonomy, config, doctor)
- ✅ 404 error page
- ✅ Auth integration (reuses existing `AuthMiddleware`)
- ✅ Redaction (reuses `RedactionHelper` from `trace/redaction.py`)
- ✅ Base layout with sidebar navigation (Jinja2 + htmx)
- ✅ Minimal CSS (responsive, mobile-aware)
- ✅ Local `htmx.min.js` (2.0.4, no CDN dependency)
- ✅ Jinja2 dependency in pyproject.toml
- ✅ `[tool.setuptools.package-data]` for templates/static files in wheel
- ✅ 30 new tests for console routes, status API, auth, redaction
- ✅ Chat page at `/console/chat` — message area, input form, htmx send, SSE streaming endpoint
- ✅ Chat send (`POST /console/chat/send`) reuses RuntimeKernel, returns HTML partial with user/assistant bubbles + trace metadata
- ✅ Chat stream (`POST /console/chat/stream`) returns SSE events (metadata/delta/final/error)
- ✅ HTML escape + redaction on all dynamic content
- ✅ AuthMiddleware protects chat routes (401 without valid key)
- ✅ Console‑default session (`console-default`), auto‑created workspace
- ✅ Session sidebar with create/list/switch/archive/delete
- ✅ History recovery on page refresh (messages loaded from DB)
- ✅ User messages persisted in DB (auto-title from first message)
- ✅ Chat session routes: `GET/POST /console/chat/sessions`, `GET/POST /console/chat/sessions/{id}/archive|delete`
- ✅ Audit logging for all session mutations
- ✅ 17 new tests for chat page, API, streaming, XSS, redaction, auth
- ✅ 32 new tests for multi-session chat
- ✅ Trace & Audit pages (Phase 5)
- ✅ Autonomy pages (Phase 6)
- ✅ Config page & Doctor page (Phase 7)

v0.13.0-dev (Workspace Files + Artifact System):
- WorkspaceFileRegistry with root registration, file CRUD, path traversal/symlink escape prevention, SHA256 hashing, fnmatch ignore patterns
- FileIngestionService with idempotent scan, text extraction (.txt/.md/.json/.py/.ts/.js), encoding fallback, max file size limit
- Chunk index with FTS5 (file_chunks_fts): 512-char chunks, 64-char overlap, path/line-number metadata
- FileRetriever.search() with FTS5 primary + MockEmbeddingService fallback for semantic search
- ArtifactService with CRUD + render (markdown/json/text) + audit log integration + trace spans
- 5 new file capability manifests: workspace.file.scan/.search/.read/.write_artifact/.remove_from_index
- ContextEngine file_context integration: FileRetriever results as ContextItem with source_lineage
- Console pages: /console/workspace/files (list/scan/reindex/remove), /console/artifacts (list/detail/download/delete)
- Upgraded project_status builtin skill: collects memories/sessions/inbox/file chunks → Markdown artifact + inbox notification
- Migration v9: workspace_roots, workspace_files, file_chunks, file_chunk_embeddings, file_chunks_fts, artifacts
- FILE_POLICY_RULES for stricter background/scheduler file operations
- Audit log() now returns audit_id string
- 44 new tests, 1146 tests passing, ruff clean, mypy clean (95 source files)
- docs/22_V0_13_WORKSPACE_FILES_ARTIFACTS_PLAN.md created

v0.14.0-dev (Real Skills + Drift Runtime, current):
- 5 built-in skills upgraded from stubs to real implementations:
  - **daily_brief**: collects memories/tasks/sessions/inbox/artifacts/file_chunks → Markdown artifact + inbox notification; ContextEngine integration; trace/audit
  - **memory_consolidation**: finds duplicates (identical text), stale (≥30 days), conflicting (negation-based), low-confidence (<0.3) memories → JSON proposal artifact; proposal-only (NO direct merge/archive/delete); inbox notification; trace/audit
  - **task_extraction**: extracts candidates from sessions/task memories/pending inbox/recent artifacts → JSON candidate artifact; does NOT write task memories; inbox notification; trace/audit
  - **trace_review**: analyzes failed traces/denied calls/unresolved approvals/slow calls/high-cost calls/dead-letters/file errors/skill failures → Markdown health report artifact; inbox notification; trace/audit
  - **inbox_digest**: aggregates unread inbox items, merges duplicates by normalized key, identifies noisy sources (>30% ratio, ≥3 count) → Markdown digest artifact; does NOT create inbox notification (no recursive spam)
- SkillRunner updated: SkillRunLog tracks output_types, artifact_ids, inbox_item_ids, proposal_ids
- DriftRuntime with daemon tick loop (60s interval), skill selection (low-risk first: memory_consolidation/trace_review/inbox_digest, then medium-risk: daily_brief/task_extraction with 2x cooldown), quiet hours, daily budget (default 5), per-skill cooldown (300s/600s), pause/resume with reason, trace/audit per run, drift_runs table persistence, status() API, update_settings() API
- DriftMaintenance with consolidate_memories, archive_stale_memories, refresh_fts, cleanup_traces, usage_report
- Console Drift page: /console/drift dashboard (status/budget cards, pause/resume, run history), /console/drift/runs/{id} detail (trace/artifact/audit links)
- Migration v10: drift_runs, drift_state tables
- 47 new tests, 1192 tests passing, ruff clean, mypy clean (112 source files)
- docs/23_V0_14_REAL_SKILLS_DRIFT_RUNTIME_PLAN.md created

## V2 Status

- ✅ All V2 items except cloud migration adapters (deprioritized)

## Project Purpose

Local-first personal Agent runtime with long-term memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior.

## Implementation Order (Epic sequence from backlog)

1. Bootstrap (package, ruff, mypy, pytest config)
2. Shared types/schemas (RuntimeEvent, turn state, manifests)
3. Storage layer (SQLite, repositories, workspace filtering)
4. Trace & audit (spans, model/tool call logs, redaction)
5. Runtime kernel (state machine, turn lifecycle, budget)
6. Policy engine (static matrix, approval, deny)
7. Capability registry (manifest loader, validation, safe tools)
8. Memory & context (FTS5 retrieval, candidates, ranking)
9. CLI chat loop (session, inline approval, display)
10. API chat endpoint (FastAPI, after CLI is stable)
11. Model provider adapter (OpenAI-compatible or Ollama)
12. E2E local demo
13–14. Skill & autonomy (V1, after MVP)
15. Autonomy Plane MVP (v0.7)

Each epic depends on previous ones. Do not skip ahead.

## Forbidden Dependencies

- `runtime` must not import concrete model providers, tool implementations, storage drivers, or UI channels.
- `capability` must not bypass `governance` (policy/approval).
- `memory` must not directly call models.
- `api` must not write storage except through application services.

## Package Boundaries

```
src/cogito_agent/
  runtime/     — turn lifecycle, state machine, orchestration
  models/      — provider-neutral model interface
  storage/     — tables, repositories, migrations
  memory/      — memory entities, lifecycle, retrieval
  context/     — context ranking, trimming, lineage
  capability/  — manifests, registry, invocation interface
  governance/  — policy, approvals, audit decisions
  trace/       — trace/span/model/tool logs
  cli/         — channel adapter (CLI)
  api/         — channel adapter (FastAPI)
tests/
docs/
```

## Private Directories

Do not read, modify, or reference `docs_zh/`, `private/`, `.local/`, or `secrets/` unless the user explicitly asks.

## What Not to Overbuild (MVP)

No cloud sync, plugin marketplaces, distributed queues, multi-agent orchestration, UI clients (TUI/Web), proactive notifications, background skill execution, scheduler, or MCP integration.

Note: v0.7 adds constrained proactive behavior via Autonomy Plane MVP. This is limited to CLI-only, local outbox (no real push), deterministic rules (no LLM judge), and no Web UI.

## Tech Stack

- Python 3.12+, Pydantic, SQLite (no ORM unless schema grows complex)
- pytest, Ruff, mypy
- FastAPI only after CLI MVP is stable
- SQLite FTS5 for MVP retrieval (no vector yet)

## Testing Expectations

Add tests with each behavioral change. Security/approval/audit/deletion paths require negative tests. New public functions should be typed.

## If Docs Conflict

Lower-numbered spec wins for product scope; more specific spec wins for implementation details. Chinese architecture doc is reference material, not an implementation contract.

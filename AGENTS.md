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

v0.8.0-dev (Console MVP Phase 1–6, current):
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

## Verification Status

- **935 tests passing** (`pytest` clean)
- **ruff clean** (`ruff check src/` clean)
- **mypy clean** (`mypy src/` clean, 88 files)

## Architecture Completion Status (docs/07_ARCHITECTURE_COMPLETION_PLAN.md)

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

## Console Status (v0.8 Phase 1–2)

- ✅ Console module structure (`src/cogito_agent/console/`)
- ✅ Dashboard at `/console/` with stat cards, system info, quick links
- ✅ Status API at `/api/v1/status` with counts, DB health, provider info, secrets info
- ✅ 8 placeholder pages (chat, memory, approval, traces, audit, autonomy, config, doctor)
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
- ✅ 17 new tests for chat page, API, streaming, XSS, redaction, auth
- ✅ Trace & Audit pages (Phase 5)
- ✅ Autonomy pages (Phase 6)
- 🚧 Config page (Phase 7)

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

# Changelog

## v0.9.0-dev (2026-06-17)

### **Multi-Session Chat + History Recovery**

- **Fixed kernel swapped args bug**: `_build_context` and `_build_model_messages` called `list_by_session(workspace_id, session_id)` but the method signature is `list_by_session(session_id, workspace_id)` — context building was silently broken
- **User messages persisted**: previously only assistant responses were saved to the `messages` table; now user messages are also persisted before the assistant reply
- **Auto-title**: session title auto-set from first user message (first 80 chars)
- **Session sidebar**: left sidebar in the chat layout showing all sessions with title, message count, and last message preview
- **Create session**: `POST /console/chat/sessions` — creates a new UUID-based session, appends to sidebar
- **List sessions**: `GET /console/chat/sessions` — returns full session list HTML partial
- **Get session with messages**: `GET /console/chat/sessions/{id}` — returns all messages as `chat_history.html` partial
- **Archive session**: `POST /console/chat/sessions/{id}/archive` — soft delete via `deleted_at`
- **Delete session**: `POST /console/chat/sessions/{id}/delete` — hard delete (removes messages, spans, traces, and session)
- **History recovery on page refresh**: `GET /console/chat` loads messages from DB on page load via htmx, no more blank chat area
- **Audit logging**: session created/archived/deleted all write audit log entries
- **CSS**: responsive session sidebar with hover actions, active state, overflow scrolling
- **Bugfix**: `SessionRepository.hard_delete` now deletes spans before traces (foreign key fix)
- **32 new tests**: session CRUD, persistence, audit logs, auth protection, redaction/XSS, archive/delete, empty state, multi-session isolation
- **1043 tests passing**, ruff clean, mypy clean (91 source files)
- **docs/18_V0_9_MULTI_SESSION_CHAT_PLAN.md** created

## v0.8.0 (2026-06-17)

### **Console MVP Phase 8 — Polish & RC Hardening**

- **Nav active state**: sidebar now highlights current page via `request.url.path` comparison
- **Dashboard quick links**: removed all "coming soon" labels (all pages are real now)
- **CSS polish**: UUID/code wrapping (`word-break: break-all`), raw JSON scroll (`overflow-x: auto`), empty state styling, responsive improvements (sidebar, stat cards, tables, filters), button styles (accept/reject/archive/delete/view/filter)
- **Loading states**: global htmx indicator (`#global-indicator`) for all htmx actions, CSS opacity (`button.htmx-request`) for visual feedback
- **Critical bugfix**: `<!DOCTYPE html>` before `{% extends %}` in `traces.html` and `trace_detail.html` removed (causes Jinja2 `TemplateSyntaxError`)
- **Error page**: returns 404 with console layout for unknown pages
- **Security regression**: 73 new unified tests in `test_console_security_regression.py` covering:
  - Auth blocks all 9 console pages + 2 API endpoints without token
  - Auth allows valid Bearer token on all pages
  - Auth blocks wrong Bearer token on all pages
  - No secret value leak (password, token_value) on any page
  - No API key pattern leak (`sk-[a-zA-Z0-9]{10,}`)
  - No Bearer token credential leak
  - No stack trace / file path leak on any page
- **1011 tests total**, ruff clean, mypy clean (90 source files)

### Added

- **Console MVP Phase 1**: FastAPI+Jinja2+htmx Web Console at `/console/`
- **Dashboard**: stat cards (memories, pending approvals, outbox, decisions/audit/traces 24h), system info (DB, provider, secrets), quick links
- **Status API**: `/api/v1/status` returns JSON with version, DB health, model config, secrets backend, counts, limitations
- **8 placeholder pages**: Memory, Approvals, Traces, Audit, Autonomy, Config, Doctor — all with "coming soon" message
- **404 error page**: rendered via Jinja2 template
- **Auth integration**: `COGITO_API_KEY` Bearer auth protects console routes automatically via existing `AuthMiddleware`
- **Redaction**: `console/redaction.py` reuses `RedactionHelper` from `trace/redaction.py`
- **Templates**: base layout with sidebar nav, dashboard, error, placeholder, component partials (`stat_card.html`, `status_badge.html`, `flash_message.html`)
- **Static files**: `console.css` (responsive, mobile-aware), local `htmx.min.js` (2.0.4, no CDN)
- **Packaging**: Jinja2 >= 3.1 and python-multipart dependencies, `[tool.setuptools.package-data]` for templates/static in wheel
- **30 new tests**: console routes, status API JSON fields, auth (no-key/wrong-key/valid-key), redaction
- **82 source files** (+4 new: `console/__init__.py`, `console/router.py`, `console/status.py`, `console/redaction.py`)

### **Console MVP Phase 7 — Config Viewer & Doctor Page**

- **Config viewer** (`GET /console/config`) — read-only section-grouped config table (Environment, Model Provider, Secrets, Autonomy, Auth & Console), all content redacted (API keys, Bearer tokens, passwords) via `redact_html()`, HTML-escaped via Jinja2 `| e`
- **Doctor page** (`GET /console/doctor`) — system health check with section-grouped results (core, database, provider, secrets, governance, autonomy, console), overall status badge (ok/warning/error)
- **Doctor JSON API** (`GET /api/v1/doctor`) — returns JSON with status, checks, limitations; `?live=1` returns 501 (not implemented in console viewer)
- **Doctor checks**: app version, Python/platform, config load, package availability, DB reachability/schema version/table counts, provider registration/model config/secret resolution, secrets backend availability, PolicyEngine/ApprovalRepository/AuditLogger/Tracer availability, recent audit count, recent traces count, autonomy store availability, template availability, static asset availability, htmx presence, auth middleware status, known limitations
- **Live provider check**: skipped by default; use `cogito provider test <name> --live` on CLI
- **Shared modules**: `config_views.py`, `doctor_views.py` keep `router.py` clean
- **Templates**: `config.html` (section-grouped tables), `doctor.html` (overall status badge + section check cards)
- **CSS**: `.cfg-section` / `.doc-section` section grouping, `.doc-card` check cards, `.doc-badge` status badges (ok/warning/error)
- **Route registration**: both routers mounted before `/{page}` catch-all, "config" and "doctor" removed from placeholder list
- **Menu items**: "Config" and "Doctor" now link to real pages (no "soon" badge)
- **Status API updated**: limitations now show "Config viewer is read-only in v0.8 Phase 7"
- **Known limitations**: no config editing, no live provider check UI, no advanced diagnostics, no diagnostic bundle export
- **Pre-existing ruff line-length issues in doctor_views.py fixed in this phase**
- **New API**: `GET /api/v1/doctor` returns JSON with status, checks, limitations; `?live=1` returns 501 (4 tests)
- **938 tests total**, ruff clean, mypy clean (90 source files)

### **Console MVP Phase 6 — Autonomy Console MVP**

- **Autonomy dashboard** (`GET /console/autonomy`) — stat cards (decisions total/24h, push/skip/defer/require_approval, outbox pending/sent/failed, feedback useful/too_many/wrong_time), quick links
- **Decisions list** (`GET /console/autonomy/decisions`) — stat cards (total/push/skip/defer/require_approval), filter bar (action, search, time range), cards with action badge, cost/priority scores, tags (dedup/quiet/quota/needs_approval), trace_id link
- **Decision detail** (`GET /console/autonomy/decisions/{id}`) — full decision metadata table, related outbox messages table, related feedback table, feedback submission form (5 FeedbackValue options), trace_id link, redacted raw JSON
- **Feedback submission** (`POST /console/autonomy/decisions/{id}/feedback`) — validates against FeedbackValue enum (422 on invalid), checks decision exists (404 if not), writes to FeedbackStore, writes audit log, redirects back to decision detail
- **Outbox list** (`GET /console/autonomy/outbox`) — stat cards (total/pending/sent/failed), filter bar (status, search, time range), cards with status badge, title preview, decision_id link
- **Outbox detail** (`GET /console/autonomy/outbox/{id}`) — full metadata table with decision_id/trace_id links, redacted body in pre block, redacted raw JSON
- **Feedback list** (`GET /console/autonomy/feedback`) — stat cards (total/useful/not_useful/too_many/wrong_time/irrelevant), filter bar (value, decision_id, time range), cards with value badge and decision_id link
- **Store extensions**: `DecisionStore.count_by_action()`, `DecisionStore.list_decisions_filtered()`, `Outbox.list_messages_filtered()`, `Outbox.count_by_status()`, `FeedbackStore.list_feedback()`, `FeedbackStore.count_by_value()`
- **CSS namespace `aut-`**: stat cards, filter bars, card layout, badges (push/skip/defer/require_approval/pending/sent/failed/skipped/useful/not_useful/too_many/wrong_time/irrelevant), tags, raw JSON block, feedback form styling
- **Route registration**: autonomy router mounted before placeholder catch-all, "autonomy" removed from placeholder list
- **Menu**: "soon" badge and "coming soon" removed from Autonomy in sidebar and dashboard quick links
- **Updated limitations**: status.py now shows "No real Telegram/Feishu delivery for outbox" and "Config and Doctor pages are still placeholders"
- **49 new tests**: dashboard stat cards/quick-links, decisions list (filters/search), decision detail (trace/outbox/feedback links/404/XSS), feedback post (all values/invalid/404), outbox list (filters/search), outbox detail (decision/trace links/404/XSS), security (redaction of API keys/Bearer tokens/raw JSON), auth (blocks without token/allows with valid key on all endpoints)
- **935 tests total**, ruff clean, mypy clean (88 source files)

### **Console MVP Phase 5 — Trace & Audit MVP**

- **Trace list** (`GET /console/traces`) — stat cards (total/completed/errors), filter bar (status, time range, search), cards with span count, duration, trace ID
- **Trace detail** (`GET /console/traces/{id}`) — full metadata table, span tree with expandable/collapsible nodes (parent/child via `parent_span_id`), model calls table, tool calls table, related audit events, redacted raw JSON in collapsible section
- **Audit list** (`GET /console/audit`) — stat card (total), filter bar (actor, operation, search, time range), cards with actor, action, resource, trace_id link
- **Audit detail** (`GET /console/audit/{id}`) — full metadata table with trace_id link to trace detail, redacted details JSON
- **Shared modules**: `trace_views.py`, `audit_views.py` keep `router.py` clean — imports, mounts, and delegates all trace/audit logic
- **Span tree**: built from `parent_span_id` with recursive tree builder in `_build_span_tree()`, rendered via `span_tree.html` + `span_node.html` recursive templates
- **Chat trace link**: updated from `/console/traces?trace_id=` to `/console/traces/{trace_id}` — points to real trace detail page
- **Templates**: `traces.html`, `trace_detail.html`, `span_tree.html`, `span_node.html`, `audit.html`, `audit_detail.html`
- **Trace/Audit CSS**: stat cards, filter bar, card layout, span tree with expand/collapse, raw JSON dark theme, detail views
- **Route registration**: both routers mounted before `/{page}` catch-all, "traces" and "audit" removed from placeholder list
- **Menu items**: "soon" badge removed from Traces and Audit
- **29 new tests**: trace list (filters, display), trace detail (span tree, 404), trace security (XSS, no stack trace), audit list (filters, display), audit detail (redaction, 404), audit security (XSS, no stack trace), auth (traces + audit), integration (chat trace link)
- **886 tests total**, ruff clean, mypy clean (87 source files)

### **Console MVP Phase 4 — Approval Queue MVP**

- **Approval list page** (`GET /console/approval`) — stat cards (total/pending/approved/rejected), filter bar (status/search), cards with approve/reject/view actions
- **Approval detail page** (`GET /console/approval/{id}`) — full metadata table, approve/reject forms with optional reason
- **Approve** (`POST /console/approval/{id}/approve`) — delegates to `ApprovalRepository.resolve()`, idempotent (double-process returns clear error)
- **Reject** (`POST /console/approval/{id}/reject`) — delegates to `ApprovalRepository.resolve()`, idempotent
- **All mutations write audit log**: `approval.approve` / `approval.reject` with full details (capability, resource, decision_before/after, reason)
- **Templates**: `approval.html` (list + stats + filters + cards), `approval_detail.html` (detail + action forms), `components/approval_success.html`
- **Approval CSS**: stat cards, filter bar, card layout, badges (pending/approved/rejected), detail view, action forms
- **Route registration**: `approval_router` imported and mounted before `/{page}` catch-all, "approval" removed from placeholder list
- **Menu item**: "soon" badge removed from Approvals
- **29 new tests**: page rendering (list, stats, filters, search, 404), action endpoints (approve/reject, idempotency, double-process, 404), audit logging, security (no stack trace, no secret leak, redaction, XSS escape, auth)
- **859 tests total**, ruff clean, mypy clean (85 source files)

### **Console MVP Phase 3 — Memory Review MVP**

- **Memory list page** (`GET /console/memory`) — stat cards (total/pending/active/archived/stale), filter bar (status/search), tabs (All/Candidates/Memories), cards with accept/reject/archive/delete actions
- **Memory detail page** (`GET /console/memory/{id}`) — shows full content, metadata, editable form, action buttons (accept/reject for candidates, edit/archive/delete for memories)
- **Accept candidate** (`POST /console/memory/candidates/{id}/accept`) — delegates to `MemoryCandidateRepository.accept()`, writes audit log
- **Reject candidate** (`POST /console/memory/candidates/{id}/reject`) — delegates to `MemoryCandidateRepository.reject()`, writes audit log
- **Edit candidate** (`POST /console/memory/candidates/{id}/edit`) — direct SQL update + audit log with before/after text preview
- **Edit memory** (`POST /console/memory/{id}/edit`) — delegates to `MemoryRepository.edit_text()`, writes audit log
- **Archive memory** (`POST /console/memory/{id}/archive`) — delegates to `MemoryRepository.archive()`, writes audit log
- **Delete memory** (`POST /console/memory/{id}/delete`) — delegates to `MemoryRepository.soft_delete()`, writes audit log with text preview
- **Shared utils**: `menu_items()` extracted to `utils.py` to avoid circular imports between router and memory modules
- **Templates**: `memory.html` (list + stats + filters + tabs + cards), `memory_detail.html` (detail + edit form), `components/memory_success.html`
- **Memory CSS**: stat cards, filter bar, tabs, card layout, badges, action buttons, detail view, edit form
- **Memory route ordering**: `memory_router` registered before `/{page}` catch-all to avoid placeholder conflict
- **30 new tests**: page rendering (list, stats, filters, tabs, search, 404), action endpoints (accept/reject/edit/archive/delete, idempotency, 404), security (no stack trace, no secret leak, redaction, auth)
- **831 tests total**, ruff clean, mypy clean (84 source files)

### **Console MVP Phase 2 — Chat MVP**

- **Chat page** at `/console/chat` — message area with user/assistant bubbles, input form with htmx non-streaming send
- **Chat send API** (`POST /console/chat/send`) — reuses `RuntimeKernel.process()`, returns HTML partial with user message + assistant reply + trace metadata (trace_id, request_id, state)
- **Chat stream endpoint** (`POST /console/chat/stream`) — SSE streaming via `RuntimeKernel.process_stream()`, consumes `model.streaming_enabled` and `model.max_retries` config
- **Chat templates**: `chat.html`, `components/chat_message.html`, `components/error_banner.html`
- **Chat CSS**: message bubbles (user right-aligned blue, assistant left-aligned white), scrollable message area, loading spinner, error banner
- **Session handling**: auto-creates `console-default` session and `default` workspace on first access; supports custom `session_id` / `workspace_id` via form fields
- **Error handling**: all errors redacted before display; error banners show without stack traces; 422 on empty messages
- **Security**: HTML escape via Jinja2 `| e` filter on all user/assistant content, `RedactionHelper` on all dynamic text, AuthMiddleware protects all chat routes
- **17 new tests**: chat page render, send API, SSE streaming, XSS prevention (script injection), secret redaction, auth enforcement

### Changed

- Agent version to `0.8.0-dev`
- FastAPI app now mounts console router at `/console/` and status router at `/api/v1/status`
- Chat menu item no longer shows "soon" badge
- Removed "chat" from placeholder pages list (now real route)

## v0.7.0-rc1 (2026-06-17)

### Added

- **Autonomy Plane MVP**: Notification Gate, Decision Store, Outbox, Feedback Store, Proactive Loop
- **AutonomyEvent** model with AutonomySourceType (scheduler/drift/webhook/memory/manual/system) and PriorityLevel (low/normal/high/urgent)
- **NotificationGate** with rule-based `evaluate()`: quiet hours, daily/hourly quota, dedup window, deterministic cost score, governance check
- **NotificationDecision** rich object with action (push/skip/defer/require_approval), reason_code, cost_score
- **DecisionStore** for persistent `notification_decisions` table
- **Outbox** for local pending/sent/failed message queue (`outbox_messages` table)
- **FeedbackStore** with FeedbackValue enum (useful/not_useful/too_many/wrong_time/irrelevant), audit logging
- **ProactiveLoop** with per-step trace spans (event_received, gate.evaluate, decision.persist, outbox.push, audit.*)
- **CLI**: `cogito autonomy emit|decisions|outbox|feedback` subcommands
- **Migration v6**: `notification_decisions`, `outbox_messages`, `feedback_entries` tables with indexes
- **SpanKind.autonomous** for autonomy trace spans
- **Config keys**: autonomy.enabled, quiet_hours.\*, notification.\*, dedup.\*, feedback.\*
- **Governance rule**: `notification.send` defaults to `allow_with_audit` in MVP_MATRIX
- **Per-step trace spans**: each pipeline stage has its own span

### Changed

- Autonomy push/skip/defer/require_approval now all write audit logs
- CLI decisions/outbox display full UUIDs (was 8-char truncation)
- `_value2member_map_` private Enum API replaced with try/except in gate.py, normalizer.py, proactive_loop.py
- PolicyEngine MVP_MATRIX updated with cross-cutting `notification.send` rule

### Fixed

- Governance deny on default PolicyEngine for notification.send (was escalate→deny)
- Missing per-step trace spans in ProactiveLoop
- Line length and typing issues in autonomy modules

### Security

- All autonomous push governed by Governance Plane
- notification.send defaults to allow_with_audit
- Redaction tests added for autonomy trace/audit paths
- AuditLogger redacts details before persisting

### Tests

- 755 tests total (+10 new since v0.7.0 baseline)
- New test files: `test_governance_path.py`, `test_hardening.py`
- Governance path tests: allow/deny/require_approval through ProactiveLoop
- Hardening tests: SpanKind.autonomous, migration idempotency, redaction

### Documentation

- docs/16_V0_7_AUTONOMY_NOTIFICATION_GATE_PLAN.md created
- RELEASE_CHECKLIST.md created
- AGENTS.md updated to v0.7.0-rc1 state
- README.md updated with autonomy CLI commands

## v0.6.2 (not released)

### Added

- KeychainSecretProvider (real impl via keyring lib or platform fallback)
- `secrets.backend` config: env | local | keychain
- `get_provider_from_config()` selects provider by backend config
- `model.secret_ref` config: secret_ref > api_key_env priority
- `model.timeout_seconds` wired to adapter
- Provider `--live` health check sends auth header + config timeout
- CLI mutation audit for secrets operations

## v0.6.1 (not released)

### Added

- `streaming_enabled` enforced test coverage (6 tests)
- `max_retries` retry logic (before/after-first-delta)
- `normalize_provider_error()` with PROVIDER_* codes

## v0.6.0 (not released)

### Added

- SecretProvider protocol (EnvSecretProvider, LocalSecretsProvider)
- SecretValue wrapper with redacted str/repr
- `cogito secrets` CLI
- `streaming_enabled` config key
- `max_retries` config key

## v0.5.0 (not released)

### Added

- True per-token streaming (StreamEvent/StreamGenerator)
- SSE endpoint with delta events
- `supports_streaming` adapter capability

## v0.3.0 (not released)

### Added

- Memory V2: FTS5, candidates, lifecycle, ranking
- Skill V2: approval, conditions, replay, execution controls
- Autonomy V2: scheduler, drift maintenance
- API hardening, secret redaction

## v0.2.0-alpha (released)

- Memory V1
- Skill V1
- CLI chat loop

## v0.1.0-alpha (released)

- Bootstrap
- Storage layer
- Runtime kernel
- Policy engine
- Tool dispatch

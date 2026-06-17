# Changelog

## v0.8.0-dev (2026-06-17)

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

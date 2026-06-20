# Changelog

## v0.16.0-dev (2026-06-19)

### Baseline stabilization

- Centralized application version reporting in `cogito_agent.version.APP_VERSION`; API, Console,
  Doctor, status and backup manifests now report `0.16.0-dev` consistently.
- File logging falls back to structured stdout when the local log directory is not writable.
- Fixed the remaining Django-only `yesno` filters in the Drift Jinja template and restored the
  Dashboard migration status row.
- Added optional real-browser Console smoke-test scaffolding and documented the verified project
  baseline in `docs/26_PROJECT_BASELINE_AUDIT.md`.
- Verified locally: 1433 tests passed, 4 skipped; Ruff clean; Mypy clean for 134 source files.
- Added validated `cogito config init`, wheel resource contract tests, and a Windows/Linux/macOS
  Python 3.12/3.13 CI matrix.
- Hardened `cogito-daemon` with persistent configuration, atomic PID locking, graceful signals,
  systemd/launchd definitions, and optional pywin32 service support.
- Added checksum-verified backup/restore, restore safety copies, migration pre-backups,
  scheduled SQLite maintenance/backups, and redacted diagnostic bundles.
- Added the provider-neutral Model Router and RoutedModelAdapter with deterministic constraints,
  fallback ordering, health cache, circuit breaker, recovery probe, and streaming safeguards.
- Wired configured providers through ModelRouter and persisted route decisions, exclusions,
  failed attempts, fallback selection, and successful selection to Trace/Audit with redaction.
- Added evidence-aware ContextItems, migration-backed context metadata, immutable incremental
  session summaries, and a structured ResultComposer integrated into Runtime turns.
- Added the three-column Chat Workspace, paginated sessions/messages, allowlisted Markdown,
  Tool/Approval cards, stop/retry controls, audited rename/branch operations, and a workspace-scoped
  Turn Inspector for trace, model, tool and governance records.

### **Console Architecture Foundation (Phase 0)**

- **ConsolePageContext TypedDict**: Unified typed context for all console pages with `Breadcrumb`, `FlashMessage`, `MenuItem`, `SystemStatusSummary`, `WorkspaceSummary` subtypes. `src/cogito_agent/console/context.py`.
- **BaseConsoleService**: Abstract service boundary with `build_page_context()` interface, ensuring all pages share consistent ViewModel construction. `src/cogito_agent/console/services/base.py`.
- **DashboardService**: Concrete implementation migrating dashboard from raw `dict[str, object]` to typed `ConsolePageContext`. Router now delegates context building to service. `src/cogito_agent/console/services/dashboard.py`.
- **Static Resource Versioning**: `?v={sha256[:12]}` appended to `console.css` and `htmx.min.js` URLs via new `static_version.py` module and `static_version` Jinja2 global. Cache-busting on every static file change.
- **22 new tests**: TypedDict conformance, DashboardService unit, static version determinism, integration (dashboard route serves versioned CSS/JS). `tests/test_v0_16_phase0.py`.

### **Design System (Phase 1)**

- **Design Tokens CSS**: 85-line `design-tokens.css` with color palette (bg/surface/primary/success/warning/danger/info/accent), typography (display/body/mono), spacing (4/8/12/16/24/32/48/64), radius (2/6/10), elevation, motion (120/180/260ms), and layout tokens. `src/cogito_agent/console/static/design-tokens.css`.
- **Component Macros**: `_macros.html` with `stat_card()`, `badge()`, `button()`, `card()`, `page_header()`, `empty_state()`, `stat_row()`. Used across chat, overview, and dashboard templates. `src/cogito_agent/console/templates/console/components/_macros.html`.
- **Icon System**: Named SVG icon sprite in `components/icons.html` with `home`, `chat`, `memory`, `approval`, `trace`, `audit`, `autonomy`, `config`, `doctor`, `inbox`, `drift`, `artifact`, `workspace`, `overview` icons. `base.html` includes sprite and renders icons via `<svg><use href="#icon-{name}"/></svg>`.
- **Base Shell Updates**: `base.html` uses design tokens CSS, responsive sidebar with RWD breakpoints, SVG icon sprite for all nav items, CSRF meta tag, security headers, flash messages via `flash_message.html` component, and 14 named menu items with active-state highlighting.
- **Error/Empty/Status Components**: `error_banner.html`, `flash_message.html`, `status_badge.html`, `memory_success.html`, `approval_success.html` for consistent UX across all pages.
- **33 new tests**: Design token CSS serving, icon sprite rendering, component macro rendering (stat_card, badge, button, card, page_header, empty_state, stat_row), base shell layout (sidebar, nav items, active state, mobile responsiveness, CSRF meta tag), empty state integration in all 14 pages, component HTML structure and aria attributes. `tests/test_v0_16_phase1.py`.

### **Overview Page (Phase 2)**

- **ConsoleOverviewService**: Full service implementing `BaseConsoleService` with 7 data aggregation methods:
  - `_get_attention_queue()` — pending approvals, failed deliveries, pending memory candidates, failed drift runs.
  - `_get_runtime_health()` — db_ok, provider status, streaming, secrets, drift_ok, scheduler (stub).
  - `_get_activity_stream()` — unified timeline from traces, drift runs, autonomy decisions, artifacts.
  - `_get_usage_snapshot()` — model calls (24h/7d), tool calls (24h/7d), avg latency, failure rate, total traces, decisions.
  - `_get_quick_actions()` — New Chat, Run Skill, Scan Workspace, Create Backup (with `soon` badge).
  - `build_page_context()` assembles all sections into typed `ConsolePageContext`.
  - Uses raw SQL for tables without repository wrappers; uses existing repos where available.
  - `src/cogito_agent/console/services/overview.py`.
- **Overview Template**: `overview.html` extends `base.html`, uses component macros. Five sections with aria-labels: Attention Queue (color-coded items), Runtime Health (5 indicators with health dots), Quick Actions (action cards), Activity Stream (timeline with colored dots), Usage Snapshot (stat_row macro). Inline CSS (`.ov-section`, `.ov-attention-items`, `.ov-health-grid`, `.ov-actions`, `.ov-timeline`). Empty states for attention queue and activity stream. `src/cogito_agent/console/templates/console/overview.html`.
- **Route & Navigation**: `GET /console/overview` in `router.py`, Overview link with "check" icon in sidebar `menu_items()`, SVG path for check icon in `base.html` icon sprite.
- **Bugfix**: `drift.html` fixed `{% empty %}` (django-ism) → `{% else %}` (Jinja2) and `truncatechars:12` → `truncate(12, True)` (colon-syntax).
- **50 new tests**: Route returns 200, HTML structure, all 5 sections present, empty states ("All clear", "No recent activity"), navigation check, runtime health indicators, quick actions with "soon" badge, activity stream timeline, usage snapshot metrics, service-level tests with seeded database (attention queue, usage snapshot, activity stream, drift health), existing 14 routes regression. `tests/test_v0_16_phase2.py`.
- **105 tests total** across v0.16 phases (22 + 33 + 50), 1300+ full suite passing.

## v0.15.0-dev (2026-06-19)

### **Production Foundation**

- **TOML Config File**: New `~/.cogito/config.toml` supported with priority chain: CLI args > environment variables > config file > built-in defaults. Backward compatible with existing JSON/YAML config files. `src/cogito_agent/config/loader.py`.
- **Structured JSON Logging**: Rotating file handler writes JSON-formatted logs to `~/.cogito/logs/cogito.log`. Configurable via `logging.level`, `logging.format`, `logging.max_size`, `logging.backup_count`. Uses `python-json-logger`. `src/cogito_agent/logging/__init__.py`.
- **Health Endpoint**: `GET /api/v1/health` returns 200 with `{"status": "ok", ...}` when database and config are healthy, returns 503 when critical dependencies fail. `src/cogito_agent/api/app.py`.
- **SQLite WAL + busy_timeout**: All `Database()` connections now set `PRAGMA busy_timeout=5000` for reliable concurrent access. Existing WAL mode and migration compatibility preserved. `src/cogito_agent/storage/database.py`.
- **CORS Allowlist**: Changed from wildcard `["*"]` to allowlist with localhost origins by default. Configurable via `security.cors_origins` in config file or `COGITO_CORS_ORIGINS` env var. `src/cogito_agent/api/app.py`.
- **CSRF Protection**: New `CSRFMiddleware` protects all console state-changing endpoints. Token passed via meta tag in base template, automatically injected into htmx headers. Exempt paths for API/health endpoints. Configurable via `security.csrf_enabled`. `src/cogito_agent/api/app.py`.
- **Security Headers**: `SecurityHeadersMiddleware` adds `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY`, `Content-Security-Policy` with strict defaults including `frame-ancestors 'none'`. `src/cogito_agent/api/app.py`.
- **Request Body Size Limit**: Default 10MB limit enforced via FastAPI middleware. Configurable via `security.max_request_size`. `src/cogito_agent/api/app.py`.
- **Version Sync**: `pyproject.toml`, `README.md`, `AGENTS.md`, `CHANGELOG.md` all synced to v0.15.0-dev.
- **Dependency**: Added `python-json-logger>=2.0` to project dependencies.
- **30+ new tests**: Config (TOML load, env overrides, CLI overrides, merge priority), health endpoint (200/503), logging (setup, rotation), SQLite (busy_timeout, WAL), security (CSRF, CORS allowlist, security headers, request body limit, negative tests for all). `tests/test_v0_15_production_foundation.py`.
- **1222+ tests passing**, ruff clean, mypy clean (113 source files)
- **docs/25_V0_16_ARCHITECTURE_CONSOLE_PLAN.md** updated (Section 20.2 item 1 complete)

## v0.14.0-dev (2026-06-18)

### **Real Skills + Drift Runtime**

- **5 Real Built-in Skills**: `daily_brief`, `memory_consolidation`, `task_extraction`, `trace_review`, `inbox_digest` upgraded from stubs to full implementations.

- **daily_brief**: Collects memories, tasks, sessions, inbox items, artifacts, and file chunks; generates a Markdown briefing report as an artifact; creates an inbox notification with artifact link; integrates with ContextEngine; writes audit logs and trace spans. `src/cogito_agent/skill/builtin/daily_brief.py`.

- **memory_consolidation**: `_find_duplicates` (groups by identical lowercase text, proposes merge), `_find_stale` (≥30 days old, proposes archive), `_find_conflicting` (negation-based conflict detection with ≥3 overlapping words and opposing negation), `_find_low_confidence` (<0.3 confidence, proposes flag). Outputs JSON proposal artifact with action/reason/confidence/source_memory_ids. **Proposal-only — does NOT perform any mutations**. Inbox notification. Trace/audit. `src/cogito_agent/skill/builtin/memory_consolidation.py`.

- **task_extraction**: Scans recent sessions (with title, excludes "Console Chat"), task/project memories (>20 chars), pending inbox items, and recent artifacts. Each source contributes structured candidates with title/description/source/priority/confidence/requires_confirmation. **Does NOT write task memories**. JSON candidate artifact. Inbox notification. Trace/audit. `src/cogito_agent/skill/builtin/task_extraction.py`.

- **trace_review**: Analyzes failed traces, denied tool calls, unresolved approvals (pending), slow tool calls (>10s), high-cost model calls (>30s), dead-letter outbox messages, file ingestion errors, and skill failures. Generates Markdown health report artifact with issue type, affected IDs, risk level (low/medium/high), and recommended fixes. Inbox notification. Trace/audit. `src/cogito_agent/skill/builtin/trace_review.py`.

- **inbox_digest**: Aggregates unread inbox items from DB, merges duplicates via normalized key (`source:title[:40]:body[:60]`), identifies noisy sources (>30% of total items, count ≥3). Generates Markdown digest artifact with groups, noisy sources, and recommendations. **Does NOT create inbox notifications** (no recursive spam). Trace/audit. `src/cogito_agent/skill/builtin/inbox_digest.py`.

- **SkillRunner output metadata**: `SkillRunLog` tracks `output_types`, `artifact_ids`, `inbox_item_ids`, `proposal_ids` in the persisted step log JSON. `src/cogito_agent/skill/runner.py`.

- **DriftRuntime**: Full daemon tick loop (60s interval), skill selection prioritizing low-risk skills (`memory_consolidation`, `trace_review`, `inbox_digest`) before medium-risk (`daily_brief`, `task_extraction` with 2x cooldown), quiet hours (configurable start/end), daily budget (default 5), per-skill cooldown (300s low-risk, 600s medium-risk), pause/resume with reason, trace/audit per run, `drift_runs` table persistence, `status()` API with next eligible skills, `update_settings()` API. Legacy `submit()`/`process()` kept for backward compat. `src/cogito_agent/runtime/drift.py`.

- **DriftMaintenance**: `consolidate_memories()` (delete exact duplicates, workspace-scoped or global), `archive_stale_memories()` (insert stale copies with `status='stale'`), `refresh_fts()` (rebuild FTS index), `cleanup_traces()` (purge traces/source data older than N days), `usage_report()` (count messages/memories/traces/tool_calls/audit_logs per workspace or global). `src/cogito_agent/runtime/drift.py`.

- **Console Drift Page**: `/console/drift` dashboard with status/budget stat cards, pause/resume actions, run history table with artifact/trace/audit links. `/console/drift/runs/{run_id}` detail page. All content redacted + HTML-escaped. AuthMiddleware protected. `src/cogito_agent/console/drift_views.py`, `drift.html`, `drift_run_detail.html`.

- **Migration v10**: `drift_runs` table (id, workspace_id, skill_name, status, trace_id, audit_id, artifact_id, started_at, completed_at, error_message, metadata_json, created_at) with indexes. `drift_state` table (enabled, paused, quiet_hours_start/end, daily_budget, timezone, runs_today, pause_reason, paused_at, updated_at) with default row. Export includes both tables.

- **Security fix**: `LocalSecretsProvider._init_db()` now creates parent directories automatically (fixes `unable to open database file` on Windows when `/tmp/` doesn't exist).

- **Bugfixes**: `trace_review.py` and `task_extraction.py` now properly convert `sqlite3.Row` objects to `dict` before calling `.get()`. Test fixture inserts for `workspace_files` and `file_chunks` now include `created_at`/`updated_at` columns (NOT NULL constraints from migration v9).

- **v0.14 Stabilization**: 3 new release regression tests verify `memory_consolidation` does not mutate memories directly, `_tick()` does not run during quiet hours, and `inbox_digest` does not create recursive inbox notifications. Existing quiet hours tests made deterministic (always-quiet range). All pre-existing issues documented.

- **47 new tests** (26 skill + 17 drift + 3 regression + 1 fix), **1192 tests passing**, ruff clean, mypy clean (112 source files)
- **docs/23_V0_14_REAL_SKILLS_DRIFT_RUNTIME_PLAN.md** created
- **docs/24_V0_15_PRODUCTION_PACKAGING_PLAN.md** created (draft)

## v0.13.0-dev (2026-06-18)

### **Workspace Files + Artifact System**

- **Workspace File Registry**: `WorkspaceFileRegistry` with root registration, file CRUD, path traversal/symlink escape prevention (sandboxed to registered roots), SHA256 hashing, fnmatch-based ignore patterns (`.gitignore`-style). `src/cogito_agent/workspace/registry.py`.
- **File Ingestion Service**: `FileIngestionService` with idempotent scan, text extraction for `.txt`/`.md`/`.json`/`.py`/`.ts`/`.js`, encoding fallback (UTF-8/UTF-16/latin-1), configurable max file size, ignore patterns support at scan time. `src/cogito_agent/workspace/ingestion.py`.
- **Chunk Index + FTS5 Search**: Files split into overlapping chunks (512-char, 64-char overlap), indexed in `file_chunks_fts` (FTS5) for full-text search with path/line-number metadata. `FileRetriever.search()` tries FTS5 first, falls back to `MockEmbeddingService` (hash-based 384-dim) for semantic similarity. `src/cogito_agent/workspace/retrieval.py`.
- **Artifact System**: `ArtifactService` with create/list/detail/delete operations, markdown/JSON/text render, audit log integration (`log()` now returns `audit_id`), trace spans. Artifacts can be sourced from skills, tools, or manual input. `src/cogito_agent/workspace/artifacts.py`.
- **5 New File Capabilities**: `workspace.file.scan` (scan workspace roots), `.search` (FTS5 + semantic), `.read` (read file content), `.write_artifact` (create artifacts from skill/tool output), `.remove_from_index` (remove files from index). Each with JSON Schema params, risk levels, approval requirements, audit rules. `src/cogito_agent/capability/file_capabilities.py`.
- **ContextEngine file_context**: `FileRetriever.search()` integrated into `ContextEngine.build()` — file chunks become `ContextItem` with `source=file` type and `source_lineage` metadata (path, chunk index, line range).
- **Console Workspace Files Page**: `/console/workspace/files` — list indexed workspace files with path/type/size/mtime/chunk count, scan/reindex/remove actions. `<span class="text-danger">` for failed chunks. All content redacted + HTML espaced. AuthMiddleware protected. `src/cogito_agent/console/workspace_views.py`.
- **Console Artifacts Page**: `/console/artifacts` — list all artifacts with title/type/source/created; detail view with rendered content (markdown/JSON/text); download raw content. All content redacted + HTML-escaped. AuthMiddleware protected. `src/cogito_agent/console/artifact_views.py`.
- **Upgraded `project_status` Skill**: Builtin skill that collects memories, sessions, inbox items, and file chunks; generates a comprehensive Markdown report as an artifact; creates an inbox notification with artifact link; writes audit logs and trace spans. `src/cogito_agent/skill/builtin/project_status.py`.
- **Migration v9**: New tables `workspace_roots`, `workspace_files`, `file_chunks`, `file_chunk_embeddings`, `file_chunks_fts`, `artifacts` with indexes and foreign keys. Export includes all new tables.
- **Policy**: `FILE_POLICY_RULES` added for stricter background/scheduler operations on file capabilities.
- **Audit fix**: `log()` now returns `str` (audit_id) for artifact integration.
- **44 new tests**: workspace registry (13), file ingestion (10), FTS chunks (4), artifact system (11), project_status skill (6) — covering path traversal deny, symlink escape deny, scan idempotency, encoding fallback, size limits, ignore patterns, FTS search, embedding fallback, artifact CRUD/render, real project_status run with trace/audit/inbox.
- **1146 tests passing**, ruff clean, mypy clean (95 source files)
- **docs/22_V0_13_WORKSPACE_FILES_ARTIFACTS_PLAN.md** created

## v0.11.0-dev (2026-06-18)

### **Autonomy Delivery & Local Production Hardening**

- **Secret Store Hardening**: `LocalEncryptedSecretProvider` (Fernet-encrypted SQLite, requires `cryptography`), `DevSqliteSecretProvider` (plaintext SQLite with warning). `get_provider_from_config()` defaults to `dev_sqlite`. Doctor page shows security risk level per backend. `cryptography` is optional.
- **DeliveryAdapter Abstraction**: `DeliveryAdapter` protocol, `LocalInboxDeliveryAdapter` (notifications table), `ConsoleNotificationAdapter` (inbox_items table). Standardized `DeliveryResult` model.
- **Autonomy Dispatcher**: `OutboxDispatcher` with exponential backoff (30s base, 1h cap), max 5 retries, delivery states (pending/delivering/sent/failed/retrying/dead_letter). Migration v7 adds delivery-tracking columns. Trace span and audit log per attempt. All payloads redacted. Governance check via PolicyEngine.
- **Web Console Inbox**: `/console/inbox` with stat cards, status/search/time filters, batch retry/dismiss/read/feedback. `/console/inbox/{id}` detail with trace link, raw JSON, feedback form. All content redacted + HTML-escaped. AuthMiddleware protected.
- **Backup/Restore/Export CLI**: `cogito backup create [--include-secrets]`, `cogito backup restore [--dry-run]`, `cogito export memories|traces`. Secrets excluded by default (opt-in flag required). All operations write audit logs. Preflight validation for restore.
- **27 new tests**, 1097 tests passing, ruff clean, mypy clean (95 source files)
- **docs/20_V0_11_AUTONOMY_DELIVERY_HARDENING_PLAN.md** created

## v0.10.0-dev (2026-06-18)

### **Core Runtime Hardening**

- **Hybrid Memory Search**: `EmbeddingService` now falls back to `MockEmbeddingService` when `sentence-transformers` is not installed (no more `ImportError`). `HybridRetriever.search()` uses full hybrid scoring: BM25 + cosine similarity + recency bonus + confidence bonus + pinned boost (2.0x). `MemoryRetriever.search()` tries hybrid search first, falling back to FTS5 + LIKE. `search_with_lineage()` preserved. `ContextEngine.build()` reads lineage info from memory results. All existing search behavior is backward-compatible.
- **Streaming Tool Interrupt**: `process_stream()` yields `tool_call_started` (with `tool_count` + `round`) and `tool_call_completed` (with redacted `tool_results`) SSE events during tool dispatch. Tools go through full `CapabilityRegistry` + `PolicyEngine` + `ApprovalRepository` + `AuditLogger` + `Tracer` pipeline. Output redacted via `RedactionHelper`. Approval required and budget exceeded events emitted as `approval_required` / `error` events.
- **Multi-round Tool Loop**: `RuntimeKernel` now supports `max_tool_rounds` parameter (default 3). `process()` and `process_stream()` loop model → tools → follow-up model → tools up to `max_tool_rounds`. Each round checks model/tool budget and writes trace/audit. At max rounds, returns safe termination message. `_dispatch_tools` only calls follow-up model if at least one tool was actually invoked (not denied/skipped).
- **`MockEmbeddingService`**: Deterministic hash-based embedding, 384-dim, no external dependencies. Used as fallback when `sentence-transformers` not installed.
- **Test isolation fix**: `_reset_db` fixture in `test_chat_sessions.py` now uses `sys.modules` to reset the shared `_db` singleton (previously set attribute on the FastAPI app instance due to `__init__.py` module shadowing).
- **System prompt**: Added to `_build_model_messages` — "You are a helpful personal assistant running in Cogito-Agent..."
- **CLI history fix**: Sources printing removed from per-turn `_display_result`; one-time context print at session start.
- **32 new tests**: hybrid memory (16), streaming tools (8), multi-round tool loop (8)
- **1070 tests passing**, ruff clean, mypy clean (91 source files)
- **docs/19_V0_10_CORE_RUNTIME_HARDENING_PLAN.md** created

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

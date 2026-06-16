# 09 V0.2.0 Productization Plan

## Goal

Transition Cogito-Agent from Alpha Runtime Kernel to real local use: real model configuration, minimal API security, data export UX, maintenance scheduling, CLI observability enhancement.

## Epic Completion Status

| Epic | Status | Tests Added | Key Files |
|------|--------|-------------|-----------|
| A: Real Model Config | ✅ Complete | 12 | `cli/config_manager.py` — config show/set/doctor |
| B: Minimal API Auth | ✅ Complete | 6 | `api/app.py` — AuthMiddleware via `COGITO_API_KEY` |
| C: Data Export UX | ✅ Complete | 8 | `cli/export.py` — export with include/redact/format |
| D: Drift Maintenance Scheduling | ✅ Complete | 6 | `cli/__init__.py` — daemon once/run/status, schedule list/maintenance |
| E: CLI Observability | ✅ Complete | 9 | `cli/__init__.py` — traces list/show, audit list/show, usage summary |

**Total new tests:** 41

**Final test count:** 361 passed

**Lint:** ruff clean | **Typecheck:** mypy clean (62 files)

---

## Epic A — Real Model Config

### What was done
- Created `src/cogito_agent/cli/config_manager.py`:
  - JSON config file at `~/.cogito/config.json`
  - Keys: `model.provider`, `model.base_url`, `model.model`, `model.api_key_env`
  - `get_config()`, `set_config_key()`, `doctor()` functions
- Added CLI subcommands: `cogito config show`, `cogito config set <key> <value>`, `cogito doctor`
- Wired config into `chat.py`: `RuntimeKernel` reads `model.provider` from config, creates `ModelAdapter` via `get_adapter()`
- API key read from env var only (never persisted in config file)
- `doctor` checks provider registration, base_url, model name, and api_key_env presence

### Key design decisions
- JSON format (stdlib, no extra deps)
- `model.api_key_env` stores env var name, not the actual key
- `doctor` uses `list_providers()` and `_PROVIDERS` dict for validation

### Tests
- Default config values, set/get roundtrip, unknown key error, all 4 keys
- File persistence, corrupted file recovery
- Doctor checks for mock, openai (with/without key), ollama, unknown provider
- 12 tests in `tests/cli/test_config_cli.py`

---

## Epic B — Minimal API Auth

### What was done
- Added `AuthMiddleware` to FastAPI app in `api/app.py`
- Reads `COGITO_API_KEY` from env var at request time
- Checks `Authorization: Bearer <key>` header
- If env var not set, auth is disabled (allow all)
- Wrong key → 401, correct key → pass, no header → 401

### Key design decisions
- Middleware approach (covers all endpoints at once)
- Env var read at request time (supports testing with `patch.dict`)
- No dependencies added (stdlib only)
- CLI local commands unaffected (no HTTP layer)

### Tests
- Auth disabled (no key) → any status
- Auth enabled, no header → 401
- Auth enabled, wrong key → 401
- Auth enabled, correct key → pass
- Protected endpoints (8 endpoints) without key → all 401
- Protected endpoints with key → not 401
- 6 tests in `tests/api/test_auth.py`

---

## Epic C — Data Export UX

### What was done
- Created `src/cogito_agent/cli/export.py`:
  - `export_workspace()` — exports workspace, sessions, traces (with model_calls, tool_calls, spans), memories (with candidates), audit_logs, settings, skills
  - `format_export()` — JSON output with `indent=2`
  - `--include traces --include memories --include audit` filtering
  - `--redact-secrets` (default True) via `RedactionHelper`
  - `--format json`, `--out <path>`, `--workspace <name>`
- Added CLI subcommand: `cogito export`

### Key design decisions
- Reuses existing `RedactionHelper` for consistent redaction
- Default redact = True (secrets never leak by accident)
- No new dependencies

### Tests
- Export with traces only, memories only, audit only
- Export all sections
- JSON format roundtrip
- Unknown workspace error
- Secret redaction (seeds sk- key, verifies it's missing in redacted output)
- Empty workspace does not crash
- 8 tests in `tests/cli/test_export_cli.py`

---

## Epic D — Drift Maintenance Scheduling

### What was done
- Added CLI subcommands:
  - `cogito daemon once` — runs `ProactiveEngine.run_once()`
  - `cogito daemon run` — runs `ProactiveEngine.run()` (blocking loop)
  - `cogito daemon status` — lists scheduled jobs + notification gate status
  - `cogito schedule list` — lists all scheduled jobs
  - `cogito schedule maintenance <task> --daily HH:MM --weekly <day> HH:MM`
- Fixed `SchedulerEngine.list_jobs("*")` to return all jobs (was exact match only)
- Fixed `_execute_job` policy request to use `resource="database"` for maintenance actor (was `"*"` which didn't match policy rule)

### Key design decisions
- Reuses existing `SchedulerEngine`, `ProactiveEngine`, `NotificationGate` (no new infrastructure)
- All scheduled maintenance creates trace + audit (existing behavior in `_execute_job`)
- Background actor policy enforced via existing policy matrix
- Quiet hours respected via existing `_is_quiet_hours` logic

### Tests
- Empty schedule list, list with job
- Daemon once with no jobs, with job
- Scheduled maintenance creates trace + audit log
- Duplicate execution prevention (completed job not re-executed)
- 6 tests in `tests/cli/test_schedule_cli.py`

---

## Epic E — CLI Observability Enhancement

### What was done
- Added CLI subcommands:
  - `cogito traces list [--workspace] [--status] [--days]`
  - `cogito traces show <trace_id>`
  - `cogito audit list [--workspace]`
  - `cogito audit show <audit_id>`
  - `cogito usage summary --last <period> (e.g. 7d, 30d, 1d)`
- Trace listing reuses `TraceInspector.list_traces()` with status/days filtering
- Trace show reuses `TraceInspector.get_trace_full()` + `format_trace_detail()`
- Audit list queries `audit_logs` table directly with workspace filtering
- Usage summary counts traces, model_calls, tool_calls, messages, audit_logs within time window

### Key design decisions
- Reuses existing `TraceInspector` for trace display (consistent format, redaction already applied)
- Audit queries are direct SQL (simple enough, no repository needed)
- Usage summary joins across tables for accurate counts
- All output is redacted via existing trace redaction

### Tests
- Traces list empty/with data, show detail, show not found
- Format detail contains expected sections (redacted)
- Audit list empty/with data, show detail
- Usage summary counts correct
- 9 tests in `tests/cli/test_observability_cli.py`

---

## Known Limitations

1. **MockModel still default** — `config set model.provider mock` is default; real model requires env var key
2. **API auth is single-key only** — no user management, no scopes, no rate limiting
3. **Export is workspace-scoped only** — no full-database export
4. **Daemon is blocking** — `cogito daemon run` blocks terminal; no background process management
5. **Schedule maintenance uses one_shot fallback** — if neither `--daily` nor `--weekly` given, runs once immediately
6. **Usage summary is time-window only** — no per-workspace breakdown, no trend visualization
7. **Audit log show is raw SQL dump** — no redaction on audit log values (audit logs should not contain secrets)

## Next Steps (v0.3.0+)

1. Encrypted secret store (replaces env-var-only API keys)
2. Multi-workspace dashboard (CLI TUI or web dashboard)
3. Background daemon process management (PID file, service scripts)
4. Full database export (all workspaces at once)
5. Usage trends and visualization
6. Real model integration testing (OpenAI/Ollama E2E)

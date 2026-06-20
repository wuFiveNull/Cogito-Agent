# v0.15.0 — Production Packaging Plan (DRAFT)

**Status:** 🟢 **部分实现 — v0.15 最小闭环完成 (2026-06-19)**
**Date:** 2026-06-18

---

## Goal

Harden Cogito-Agent for local production use by addressing reliability, packaging, observability, and security gaps identified during v0.14 stabilization.

---

## Proposed Items

### 1. Pip Packaging & Distribution
- [x] Verify `pyproject.toml` entry points and dependencies
- [x] Ensure console templates/static files and SQL migrations are included in wheel
- [x] Add `cogito-daemon` as a configuration-driven service wrapper
- [ ] Add `cogito` to PyPI (or keep as GitHub-only artifact)
- [ ] Move `docs_zh/`, `private/`, `secrets/` to `.gitignore` or dedicated `.gitattributes export-ignore`

### 2. Windows Packaging
- [ ] Create `setup.py` (or Keep `pyproject.toml` only) for Windows MSI or `pip install` on Windows
- [ ] SQLite version check: warn if < 3.53.2 (required by FTS5 and `CURRENT_TIMESTAMP` syntax)
- [ ] Handle Windows path conventions: `~/.cogito`, `/tmp/`, etc.
- [ ] Test `cogito migrate` on clean Windows install

### 3. Daemon & Service Management
- [x] Windows: `cogito service install` / `cogito service uninstall` using optional pywin32
- [x] Linux: systemd user unit generation (`cogito service install --systemd`)
- [x] macOS: launchd LaunchAgent generation
- [x] `cogito-daemon` handles SIGHUP/SIGTERM/SIGINT gracefully
- [x] Atomic PID file management with stale-owner recovery

### 4. Logging & Observability
- [x] Structured logging (JSON lines) for production log aggregation
- [x] Log rotation: `cogito config set logging.max_size 10MB`, `logging.backup_count 5`
- [x] Health check endpoint: `GET /api/v1/health` returns 200/503
- [ ] Prometheus metrics: `/api/v1/metrics` with counters for traces, audits, skills, drift runs

### 5. Configuration File
- [x] TOML config file at `~/.cogito/config.toml` (read on startup)
- [x] `cogito config init` creates and validates default config
- [x] Merge precedence: CLI flags > env vars > config file > defaults
- [ ] Config file watching: hot-reload on file change (or SIGHUP)

### 6. Database Maintenance
- [x] busy_timeout: `PRAGMA busy_timeout=5000` for concurrent access
- [x] WAL mode: `PRAGMA journal_mode=WAL` for concurrent read/write
- [x] Auto-vacuum and SQLite optimize/checkpoint: config driven
- [x] Bounded backup scheduler integrated with the daemon maintenance worker

### 7. Security Hardening
- [x] Configurable rate limiting on API endpoints
- [x] CORS configuration (allow specific origins)
- [x] Request size limits on API payloads
- [x] Input validation hardening (Pydantic models)
- [ ] Session timeout / expiry for console sessions
- [x] CSRF protection for console forms
- [x] CSP, X-Content-Type-Options, Referrer-Policy, frame-ancestors headers

### 8. Error Reporting
- [ ] Optional Sentry integration (`cogito config set error_reporting.provider sentry`)
- [x] Local error log with rotatable file handler
- [x] Redacted `cogito diagnostics create` bundle with DB health and bounded log tail

### 9. Multi-Arch Testing
- [ ] Test on Windows (x64), macOS (arm64), Linux (x64/arm64)
- [x] CI matrix configured for Windows/Linux/macOS and Python 3.12/3.13 (first hosted run pending)
- [ ] Address platform-specific path, encoding, and file system issues

---

## Non-Goals

- Multi-user, OAuth/RBAC, Telegram/Feishu, Plugin Marketplace, Subagent
- Cloud sync or distributed queue
- Real WebSocket push
- LLM relevance judge for autonomy (deterministic rules are sufficient for MVP)
- UI overhaul

---

## Estimated Effort

| Area | Complexity | Dependencies |
|------|-----------|-------------|
| PyPI packaging | Low | None |
| Windows packaging | Medium | Windows test machine |
| Daemon service | Medium | pywin32 / systemd knowledge |
| Logging | Low | `python-json-logger` |
| Configuration file | Medium | TOML parser (stdlib `tomllib` in 3.11+) |
| DB maintenance | Low | None |
| Security hardening | Medium | FastAPI middleware |
| Error reporting | Low | `sentry-sdk` |
| Multi-arch CI | High | CI runner setup |

---

## Release Criteria

- [ ] `pip install cogito-agent` works on Windows, macOS, Linux
- [ ] `cogito migrate` succeeds on fresh install
- [x] Service definitions and daemon wrapper are implemented; hosted platform smoke runs remain pending
- [ ] `cogito doctor` shows no security risks
- [x] 1422 tests passing, 4 skipped; Ruff clean; strict Mypy clean (132 source files)
- [x] No secrets leaked in logs, traces, audit, or backup (default)

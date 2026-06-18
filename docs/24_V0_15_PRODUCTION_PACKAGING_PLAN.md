# v0.15.0 — Production Packaging Plan (DRAFT)

**Status:** 🔵 **Draft — Not Implemented**
**Date:** 2026-06-18

---

## Goal

Harden Cogito-Agent for local production use by addressing reliability, packaging, observability, and security gaps identified during v0.14 stabilization.

---

## Proposed Items

### 1. Pip Packaging & Distribution
- [ ] Verify `pyproject.toml` entry points and dependencies
- [ ] Ensure console templates/static files are included in wheel (`package-data` already configured)
- [ ] Add `console_scripts` or `scripts` entry for `cogito-daemon` as a proper service wrapper
- [ ] Add `cogito` to PyPI (or keep as GitHub-only artifact)
- [ ] Move `docs_zh/`, `private/`, `secrets/` to `.gitignore` or dedicated `.gitattributes export-ignore`

### 2. Windows Packaging
- [ ] Create `setup.py` (or Keep `pyproject.toml` only) for Windows MSI or `pip install` on Windows
- [ ] SQLite version check: warn if < 3.53.2 (required by FTS5 and `CURRENT_TIMESTAMP` syntax)
- [ ] Handle Windows path conventions: `~/.cogito`, `/tmp/`, etc.
- [ ] Test `cogito migrate` on clean Windows install

### 3. Daemon & Service Management
- [ ] Windows: `cogito service install` / `cogito service uninstall` using pywin32
- [ ] Linux: systemd unit file generation (`cogito service install --systemd`)
- [ ] macOS: launchd plist generation
- [ ] `cogito daemon run` should handle SIGHUP/SIGTERM/SIGINT gracefully
- [ ] PID file management

### 4. Logging & Observability
- [ ] Structured logging (JSON lines) for production log aggregation
- [ ] Log rotation: `cogito config set logging.max_size 10MB`, `logging.backup_count 5`
- [ ] Health check endpoint: `GET /api/v1/health` returns 200/503
- [ ] Prometheus metrics: `/api/v1/metrics` with counters for traces, audits, skills, drift runs

### 5. Configuration File
- [ ] YAML/TOML config file at `~/.cogito/config.toml` (read on startup)
- [ ] `cogito config init` creates default config
- [ ] Merge precedence: CLI flags > env vars > config file > defaults
- [ ] Config file watching: hot-reload on file change (or SIGHUP)

### 6. Database Maintenance
- [ ] Auto-vacuum: `cogito config set storage.auto_vacuum 1` (after export/backup)
- [ ] WAL mode: `PRAGMA journal_mode=WAL` for concurrent read/write
- [ ] Backup scheduler: `cogito config set backup.schedule daily` — auto-backup on daemon tick

### 7. Security Hardening
- [ ] Rate limiting on API endpoints
- [ ] CORS configuration (allow specific origins)
- [ ] Request size limits on API payloads
- [ ] Input validation hardening (current: Pydantic models)
- [ ] Session timeout / expiry for console sessions

### 8. Error Reporting
- [ ] Optional Sentry integration (`cogito config set error_reporting.provider sentry`)
- [ ] Local error log with rotatable file handler
- [ ] Error aggregation endpoint for CLI diagnostics

### 9. Multi-Arch Testing
- [ ] Test on Windows (x64), macOS (arm64), Linux (x64/arm64)
- [ ] CI matrix for 3 platforms
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
- [ ] `cogito daemon run` works as a background service
- [ ] `cogito doctor` shows no security risks
- [ ] 1200+ tests passing, ruff clean, mypy clean
- [ ] No secrets leaked in logs, traces, audit, or backup (default)

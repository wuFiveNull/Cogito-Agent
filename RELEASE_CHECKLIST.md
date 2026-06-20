# Release Checklist

## v0.8.0-rc1 Release Checklist

### Code Quality
- [x] fresh clone install ok (`pip install -e ".[dev]"`)
- [x] pytest passes (1011 tests)
- [x] ruff check src/ passes
- [x] mypy src/ passes (90 files)

### Console Pages (all pages load with valid auth)
- [x] /console/ — Dashboard with stats and quick links
- [x] /console/chat — Chat page with send/stream
- [x] /console/memory — Memory review with accept/reject/edit/archive/delete
- [x] /console/approval — Approval queue with approve/reject
- [x] /console/traces — Trace list with filters and span tree on detail
- [x] /console/audit — Audit list with filters and redacted details
- [x] /console/autonomy — Autonomy dashboard with decisions/outbox/feedback
- [x] /console/config — Read-only config viewer (redacted secrets)
- [x] /console/doctor — System health check with section-grouped results
- [x] /api/v1/status — System status JSON
- [x] /api/v1/doctor — Doctor JSON API

### Auth & Security
- [x] AuthMiddleware protects all console pages (401 without token)
- [x] Auth works with valid Bearer token (200)
- [x] No secret leakage in any HTML output (sk-, Bearer token, password, token_value)
- [x] No API key pattern leak (sk-[a-zA-Z0-9]{10,})
- [x] No Bearer token leak (Bearer <credential>)
- [x] No stack trace in UI
- [x] XSS escape verified on all pages (per-page tests pass)
- [x] Redaction applied to all dynamic content

### Navigation & UI Polish
- [x] Sidebar nav active state highlights current page
- [x] No "coming soon" on any page
- [x] Dashboard quick links all point to real pages
- [x] Empty states present on list pages
- [x] Loading indicators on htmx actions
- [x] 404 page uses console layout
- [x] Responsive: sidebar/mobile works
- [x] UUID/code content wraps properly
- [x] Raw JSON areas scroll horizontally

### Documentation
- [x] README.md reflects Console MVP Phase 1–8
- [x] AGENTS.md reflects current state
- [x] CHANGELOG.md reflects all phases
- [x] docs/17_V0_8_CONSOLE_MVP_PLAN.md completed
- [x] RELEASE_CHECKLIST.md updated
- [x] Known limitations documented

### Release Steps
- [x] All checkboxes verified
- [x] Tag commit as v0.8.0-rc1 (official release: v0.8.0)
- [x] Push tag to origin
- [x] Create GitHub Release with changelog
- [ ] Publish to PyPI (optional)

## Known Limitations (v0.8.0-rc1)

- No multi-user / OAuth / RBAC
- No config editing (read-only)
- No real Telegram / Feishu delivery — outbox is local SQLite queue
- No outbox dispatcher UI
- No advanced diagnostics or diagnostic bundle export
- No Plugin Marketplace
- LocalSecretsProvider is unencrypted SQLite
- No cloud sync, plugin marketplace, or distributed queuing
- No LLM relevance judge — cost score is purely deterministic
- Chat supports single console-default session only
- Missing polish: loading states on some htmx actions, responsive edge cases

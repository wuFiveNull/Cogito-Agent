# Release Checklist

## v0.8.0-rc1 Release Checklist

### Code Quality
- [ ] fresh clone install ok (`pip install -e ".[dev]"`)
- [ ] pytest passes (1011 tests)
- [ ] ruff check src/ passes
- [ ] mypy src/ passes (90 files)

### Console Pages (all pages load with valid auth)
- [ ] /console/ — Dashboard with stats and quick links
- [ ] /console/chat — Chat page with send/stream
- [ ] /console/memory — Memory review with accept/reject/edit/archive/delete
- [ ] /console/approval — Approval queue with approve/reject
- [ ] /console/traces — Trace list with filters and span tree on detail
- [ ] /console/audit — Audit list with filters and redacted details
- [ ] /console/autonomy — Autonomy dashboard with decisions/outbox/feedback
- [ ] /console/config — Read-only config viewer (redacted secrets)
- [ ] /console/doctor — System health check with section-grouped results
- [ ] /api/v1/status — System status JSON
- [ ] /api/v1/doctor — Doctor JSON API

### Auth & Security
- [ ] AuthMiddleware protects all console pages (401 without token)
- [ ] Auth works with valid Bearer token (200)
- [ ] No secret leakage in any HTML output (sk-, Bearer token, password, token_value)
- [ ] No API key pattern leak (sk-[a-zA-Z0-9]{10,})
- [ ] No Bearer token leak (Bearer <credential>)
- [ ] No stack trace in UI
- [ ] XSS escape verified on all pages (per-page tests pass)
- [ ] Redaction applied to all dynamic content

### Navigation & UI Polish
- [ ] Sidebar nav active state highlights current page
- [ ] No "coming soon" on any page
- [ ] Dashboard quick links all point to real pages
- [ ] Empty states present on list pages
- [ ] Loading indicators on htmx actions
- [ ] 404 page uses console layout
- [ ] Responsive: sidebar/mobile works
- [ ] UUID/code content wraps properly
- [ ] Raw JSON areas scroll horizontally

### Documentation
- [ ] README.md reflects Console MVP Phase 1–8
- [ ] AGENTS.md reflects current state
- [ ] CHANGELOG.md reflects all phases
- [ ] docs/17_V0_8_CONSOLE_MVP_PLAN.md completed
- [ ] RELEASE_CHECKLIST.md updated
- [ ] Known limitations documented

### Release Steps
- [ ] All checkboxes verified
- [ ] Tag commit as v0.8.0-rc1
- [ ] Push tag to origin
- [ ] Create GitHub Release with changelog
- [ ] Publish to PyPI (optional)

## v0.7.0-rc1 Release Candidate (historical)

### Code Quality
- [x] fresh clone install ok (`pip install -e ".[dev]"`)
- [x] pytest passes (755 tests)
- [x] ruff check src/ passes
- [x] mypy src/ passes (78 files)

### Autonomy CLI Dogfood
- [x] `cogito autonomy emit --title "test"` works
- [x] `cogito autonomy decisions` lists decisions
- [x] `cogito autonomy outbox` lists pending messages
- [x] `cogito autonomy feedback <id> --value useful` records feedback
- [x] emit produces AutonomyEvent + NotificationDecision
- [x] push writes to outbox
- [x] skip/defer/require_approval writes to decision log
- [x] feedback binds to decision_id
- [x] no secret leakage in CLI output

### Database Schema
- [x] migration v6 creates all autonomy tables
- [x] schema initialization is idempotent
- [x] old DB upgrade preserves existing data
- [x] indexes on workspace_id, created_at, event_id, status, decision_id

### Trace / Audit
- [x] ProactiveLoop creates per-step trace spans
- [x] audit log distinguishes actor (scheduler/drift/proactive_loop/manual)
- [x] autonomous context marked with SpanKind.autonomous
- [x] push / require_approval / skip all write audit logs
- [x] decision reason_code visible in trace/replay

### Governance
- [x] notification.send goes through PolicyEngine
- [x] allow -> push
- [x] require_approval -> decision.requires_approval = True
- [x] deny -> skip with governance_denied reason_code

### Config
- [x] autonomy.enabled default = true
- [x] quiet_hours.* defaults present
- [x] notification.daily_quota/default = 5
- [x] notification.hourly_quota/default = 2
- [x] dedup.window_minutes/default = 120
- [x] feedback.enabled default = true

### Notification Gate Rules
- [x] quiet hours hit
- [x] urgent bypass quiet hours
- [x] daily quota hit
- [x] hourly quota hit
- [x] dedup hit (stable SHA256 hash)
- [x] deterministic cost score (no LLM)
- [x] governance deny
- [x] governance require_approval
- [x] all rules have stable reason_code

### Redaction / Secret Safety
- [x] CLI output uses _redact() helper
- [x] audit log redacts secrets
- [x] trace attributes don't leak secrets

### Documentation
- [x] README.md updated with autonomy CLI commands
- [x] AGENTS.md updated with v0.7.0-rc1 state
- [x] docs/16_V0_7_AUTONOMY_NOTIFICATION_GATE_PLAN.md created
- [x] CHANGELOG.md created
- [x] Known limitations documented

### Release Steps
- [x] pyproject.toml version set to 0.7.0-rc1
- [x] All checkboxes verified
- [ ] Tag commit as v0.7.0-rc1 (superseded by v0.8.0-rc1)
- [ ] Push tag to origin (superseded by v0.8.0-rc1)
- [ ] Create GitHub Release with changelog
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

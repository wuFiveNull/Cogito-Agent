# Release Checklist

## v0.7.0-rc1 Release Candidate

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
- [ ] Tag commit as v0.7.0-rc1
- [ ] Push tag to origin
- [ ] Create GitHub Release with changelog
- [ ] Publish to PyPI (optional)

## Known Limitations (v0.7.0-rc1)

- No Web UI / TUI — autonomy only via CLI
- No Telegram / Feishu real push — outbox is local SQLite queue
- No LLM relevance judge — cost score is purely deterministic (priority + quiet_hours + quota + recent feedback)
- No complex multi-agent autonomy — single ProactiveLoop, no subagent delegation
- Dedup shares state with old `notifications` table (legacy `should_notify()` code path)
- No scheduled outbox delivery — messages stay in outbox until manually marked sent/failed
- LocalSecretsProvider is unencrypted SQLite
- No cloud sync, plugin marketplace, or distributed queuing

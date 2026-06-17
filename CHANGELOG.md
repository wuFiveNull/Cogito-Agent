# Changelog

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

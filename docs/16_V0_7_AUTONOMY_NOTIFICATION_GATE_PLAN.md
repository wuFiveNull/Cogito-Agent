# v0.7 Autonomy — Notification Gate & Proactive Loop

## Status

- **Version**: v0.7.1-dev (release candidate hardening)
- **Branch**: master
- **Tests**: 745 passing, ruff clean, mypy clean (78 source files)

## What's Included

Autonomy Plane MVP provides a complete decision pipeline for autonomous notifications:

### Core Concepts

1. **AutonomyEvent** — universal input for all proactive sources:
   - Sources: scheduler, drift, webhook, memory, manual, system
   - Priority: low, normal, high, urgent
   - Dedup key: SHA256(source|title|category); explicit `dedup_key` override
   - `quiet_hours_override` flag for urgent bypass
   - Pydantic model with `build_dedup_key()`

2. **NotificationGate** — rule-based evaluation:
   - **Quiet Hours**: configurable time window (e.g. 22:00-08:00), supports `urgent_bypass_quiet_hours`, `quiet_hours_override`
   - **Daily/Hourly Quota**: enforce max notifications per day/hour
   - **Dedup**: configurable window (default 120 min), stable hash
   - **Deterministic Cost Score**: based on priority + quiet_hours + quota + recent feedback (no LLM)
   - **Governance Check**: PolicyEngine with `notification.send` capability
   - Output: `NotificationDecision` (rich object with action, reason_code, cost_score)

3. **NotificationDecision** — evaluation result:
   - Actions: push, skip, defer, require_approval
   - All rule hits recorded (quiet_hours_hit, quota_hit, dedup_hit)
   - Trace/audit integrated

4. **DecisionStore** — persistent decision log (`notification_decisions` table)

5. **Outbox** — local pending/sent/failed message queue (`outbox_messages` table)
   - Outbox is a local SQLite-based queue, NOT a real Telegram/Feishu push channel

6. **FeedbackStore** — user feedback on decisions (`feedback_entries` table)
   - Values: useful, not_useful, too_many, wrong_time, irrelevant
   - Writes audit log on each feedback

7. **ProactiveLoop** — full event processing pipeline:
   - Trace → Audit → Gate Evaluate → Decision Persist → Outbox → Audit
   - Per-step trace spans (event_received, gate.evaluate, decision.persist, outbox.push, audit.*)
   - `emit_event()` convenience method for manual CLI usage

8. **CLI commands**:
   - `cogito autonomy emit` — emit event
   - `cogito autonomy decisions` — list decisions
   - `cogito autonomy outbox` — list outbox messages
   - `cogito autonomy feedback <decision_id> --value <value>` — record feedback

### Database Tables (Migration v6)

- `notification_decisions` — decision log with indexes on workspace_id, created_at, event_id
- `outbox_messages` — outbound message queue with indexes on workspace_id, status
- `feedback_entries` — feedback records with indexes on decision_id, workspace_id

### Configuration Keys (`config_manager.py`)

```toml
[autonomy]
enabled = true

[autonomy.quiet_hours]
enabled = true
start = "22:00"
end = "08:00"
timezone = "local"

[autonomy.notification]
daily_quota = 5
hourly_quota = 2
urgent_bypass_quiet_hours = true
urgent_bypass_quota = true

[autonomy.dedup]
window_minutes = 120

[autonomy.feedback]
enabled = true
```

### Governance

All `notification.send` operations pass through `PolicyEngine`:
- Default rule: `allow_with_audit` (with audit logging)
- `require_approval` → decision.action = require_approval
- `deny` → decision.action = skip with reason_code = governance_denied

### SpanKind

New `SpanKind.autonomous` for all autonomy-related trace spans.

## Known Limitations

- **No Web UI** — autonomy events/manage only via CLI
- **No real Telegram/Feishu push** — outbox is local-only; push requires custom consumer
- **No LLM relevance judge** — cost score is purely deterministic
- **No complex multi-agent autonomy** — single ProactiveLoop, no subagent delegation
- **LocalSecretsProvider is unencrypted SQLite** — not suitable for production secrets
- **No scheduled outbox delivery** — messages stay in outbox until manually marked sent/failed
- **Dedup uses legacy `notifications` table** — shares dedup state with old `should_notify()` code path

## What Not to Build (MVP)

- Web UI / TUI
- Telegram / Feishu real push
- Plugin marketplace
- Cloud deployment
- Complex subagent autonomy
- LLM relevance judge
- Runtime Kernel refactoring

## Development Commands

```bash
pytest                          # run all tests
ruff check src/                 # lint
mypy src/                       # type check

# CLI dogfood
cogito migrate                  # init DB + run migrations
cogito autonomy emit --title "test" --priority normal
cogito autonomy decisions list
cogito autonomy outbox list
cogito autonomy feedback <id> --value useful
```

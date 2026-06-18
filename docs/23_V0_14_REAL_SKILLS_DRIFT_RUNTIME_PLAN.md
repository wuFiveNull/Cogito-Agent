# v0.14.0 — Real Skills + Drift Runtime Plan

**Status:** ✅ **Completed (v0.14.0-dev)**
**Date:** 2026-06-18
**Tests:** 1192 passing, ruff clean, mypy clean (112 source files)

---

## Summary

Upgrade 5 built-in skills from stubs to real implementations and implement DriftRuntime for background proactive behavior. All skills are proposal-only (no automatic mutations). DriftRuntime respects quiet hours, daily budget, cooldown, and pause/resume.

---

## Completed Items

### 1. daily_brief (medium risk)
- ✅ Collects memories (20 recent), tasks (20 recent, non-stale), sessions (10 recent), inbox items (20 pending), artifacts (10 recent), file chunks (10 recent + file metadata)
- ✅ ContextEngine integration for context-aware recommendations
- ✅ Markdown artifact generation with sections: summary, important items, open tasks, recommended actions, sources used
- ✅ Inbox notification (source=`skill.daily_brief`), artifact link
- ✅ Trace spans (`daily_brief_collect`) and audit logs (both data collection and artifact creation)
- ✅ Manifest in loader.py

### 2. memory_consolidation (medium risk)
- ✅ `_find_duplicates`: groups by lowercase text, proposes `merge` for groups ≥2
- ✅ `_find_stale`: memories ≥30 days with status != 'stale', proposes `archive` with age-based confidence
- ✅ `_find_conflicting`: negation-based (overlap ≥3 words, opposite negation presence), proposes `review`
- ✅ `_find_low_confidence`: confidence < 0.3, proposes `flag`
- ✅ **Proposal-only**: NO direct SQL mutations — only JSON proposal artifact
- ✅ Inbox notification (source=`skill.memory_consolidation`), artifact link
- ✅ Trace spans, audit logs, workspace isolation

### 3. task_extraction (medium risk)
- ✅ Four data sources: sessions (5 recent with title), memories (10 task/project with text >20 chars), inbox (10 pending), artifacts (5 recent with title)
- ✅ Structured candidates: title/description/source/source_id/due_date/priority/confidence/requires_confirmation
- ✅ **No automatic task memory writes** — only JSON candidate artifact
- ✅ Inbox notification (source=`skill.task_extraction`), artifact link
- ✅ Trace spans, audit logs

### 4. trace_review (medium risk)
- ✅ 8 issue types with detection criteria:
  - failed_trace: status=error (risk: high)
  - denied_tool_call: decision=deny (risk: low)
  - unresolved_approval: status=pending (risk: medium)
  - slow_tool_call: latency > 10s (risk: low)
  - high_cost_model_call: latency > 30s (risk: medium)
  - dead_letter: status=dead_letter (risk: high)
  - file_ingestion_error: status=error (risk: low)
  - skill_failure: status in failed/rolled_back (risk: medium)
- ✅ Markdown health report artifact with recommendations
- ✅ Inbox notification (source=`skill.trace_review`), artifact link
- ✅ Trace spans, audit logs

### 5. inbox_digest (low risk)
- ✅ Aggregates all unread inbox items
- ✅ `_merge_duplicates`: groups by normalized key (`source:title[:40]:body[:60]`)
- ✅ `_identify_noisy_sources`: ratio > 30% AND count ≥ 3
- ✅ `_generate_recommendations`: keep/reduce_frequency per item
- ✅ Markdown digest artifact (groups, noisy sources, recommendations)
- ✅ **NO inbox notification** — prevents recursive spam loop
- ✅ Trace spans, audit logs

### 6. SkillRunner Integration
- ✅ `SkillRunLog` tracks `output_types`, `artifact_ids`, `inbox_item_ids`, `proposal_ids`
- ✅ All skill outputs persisted in `step_logs_json` JSON payload

### 7. DriftRuntime
- ✅ Tick loop (60s interval, daemon thread)
- ✅ Skill selection: low-risk (memory_consolidation, trace_review, inbox_digest) first, then medium-risk (daily_brief, task_extraction) with 2x cooldown
- ✅ Quiet hours: configurable start/end, wraps midnight, `_in_quiet_hours()` check
- ✅ Daily budget: default 5, `_increment_runs_today()` per run
- ✅ Per-skill cooldown: 300s low-risk, 600s medium-risk
- ✅ Pause/resume with reason string
- ✅ Trace/audit per run (SpanKind.autonomous)
- ✅ `drift_runs` table persistence with status/trace_id/audit_id/artifact_id
- ✅ Status API: enabled/paused/quiet_hours/budget/runs_today/eligible_skills
- ✅ `update_settings()`: quiet_hours, daily_budget, enabled, paused
- ✅ `reset_daily_budget()`: runs_today counter reset
- ✅ `list_runs()` / `get_run()` queries
- ✅ Legacy `submit()`/`process()`/`get_result()`/`task_status()`/`list_tasks()` kept for backward compat
- ✅ Workspace isolation

### 8. DriftMaintenance
- ✅ `consolidate_memories()`: delete exact duplicate texts, workspace-scoped or global
- ✅ `archive_stale_memories()`: insert stale copies with `status='stale'` for memories ≥30 days
- ✅ `refresh_fts()`: rebuild FTS index
- ✅ `cleanup_traces()`: purge traces/source data older than N days
- ✅ `usage_report()`: count messages/memories/traces/tool_calls/audit_logs

### 9. Console Drift Page
- ✅ `/console/drift` dashboard: status/budget stat cards, pause/resume, run history table
- ✅ `/console/drift/runs/{run_id}` detail: trace/artifact/audit links
- ✅ Redaction: `redact_html()` on artifact_id, error_message
- ✅ AuthMiddleware protection
- ✅ Menu integration (sidebar "Drift" item)
- ✅ Template: `drift.html`, `drift_run_detail.html`

### 10. Migration v10
- ✅ `drift_runs` table with columns and indexes
- ✅ `drift_state` table with default row
- ✅ Export includes both tables

### 11. v0.14 Stabilization
- ✅ `test_backend_local_with_path` fixed (parent dir creation in `LocalSecretsProvider`, cross-platform temp path in test)
- ✅ Release audit: all skills proposal-only, inbox_digest no-recursive-spam confirmed, DriftRuntime respects all constraints, all outputs have artifact/inbox/trace/audit, redaction confirmed
- ✅ 3 new release regression tests: memory_consolidation no-mutation, drift quiet hours blocking, inbox_digest no-recursive-spam
- ✅ Quiet hours tests made deterministic (always-quiet range instead of time-dependent)
- ✅ Full suite: 1192 passed, 0 failed, ruff clean, mypy clean

---

## Known Limitations

1. **DriftRuntime tick loop is single-threaded**: Only one skill runs per tick. Overlapping ticks not supported (blocking `ThreadPoolExecutor` with `max_workers=2` but `_tick()` is synchronous).
2. **No LLM judge**: All skill logic is deterministic rule-based. No model call for quality assessment or relevance evaluation.
3. **memory_consolidation does NOT merge/archive/delete**: All proposals require human review via Console. No automatic clean-up path.
4. **task_extraction does NOT write task memories**: Candidates are proposals only. No auto-creation of `type='task'` memories.
5. **timezone not configurable**: Quiet hours use UTC only. `timezone` column in drift_state exists but not wired.
6. **No background process management**: `start()` creates a daemon thread — process lifecycle is tied to the Python process. No systemd/launchd integration.
7. **No drift scheduling UI**: Console Drift page is read-only for settings. No inline editing of quiet hours/budget from UI.
8. **Console notification count includes skill outputs**: daily_brief, memory_consolidation, task_extraction, trace_review all create inbox notifications, which contributes to the "noisy sources" metric in inbox_digest.
9. **`test_backend_local_with_path` was pre-existing failure**: Fixed by adding parent directory creation in `LocalSecretsProvider._init_db()`.
10. **Test directory has 200 pre-existing ruff violations** (unused imports, line length, style issues in old test files). `ruff check src/` is clean.

---

## Files Changed

### New:
- `src/cogito_agent/skill/builtin/daily_brief.py`
- `src/cogito_agent/skill/builtin/memory_consolidation.py`
- `src/cogito_agent/skill/builtin/task_extraction.py`
- `src/cogito_agent/skill/builtin/trace_review.py`
- `src/cogito_agent/skill/builtin/inbox_digest.py`
- `src/cogito_agent/runtime/drift.py` (rewritten)
- `src/cogito_agent/console/drift_views.py`
- `src/cogito_agent/console/templates/console/drift.html`
- `src/cogito_agent/console/templates/console/drift_run_detail.html`
- `tests/skill/test_real_skills.py`
- `tests/runtime/test_drift_v2.py`

### Modified:
- `src/cogito_agent/storage/database.py` (migration v10)
- `src/cogito_agent/skill/builtin/loader.py` (register all 6 manifests)
- `src/cogito_agent/skill/runner.py` (SkillRunLog output_types)
- `src/cogito_agent/console/router.py` (mount drift_router)
- `src/cogito_agent/console/utils.py` (Drift menu item)
- `src/cogito_agent/security/secrets.py` (parent dir creation)
- `AGENTS.md`, `README.md`, `CHANGELOG.md`

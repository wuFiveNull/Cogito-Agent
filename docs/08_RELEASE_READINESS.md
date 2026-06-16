# 08 Release Readiness — v0.1.0-alpha

## Version

**v0.1.0-alpha candidate** (commit `d6961fe`)

## Verified Commands

| Command | Status | Notes |
|---------|--------|-------|
| `cogito --help` | ✅ | Displays migrate, chat, replay, maintenance |
| `cogito migrate` | ✅ | Creates `~/.cogito/cogito.db` and all tables |
| `cogito chat` | ✅ | Interactive session with trace_id + state display |
| `cogito replay list` | ✅ | Lists traces across all workspaces |
| `cogito replay show <id>` | ✅ | Shows full trace (state path, model/tool calls, policy, lineage, context) with redaction |
| `cogito maintenance usage` | ✅ | Creates trace + audit log |
| `cogito maintenance consolidate` | ✅ | Deduplicates memories, creates trace + audit |
| `cogito maintenance archive` | ✅ | Archives stale memories, creates trace + audit |
| `cogito maintenance refresh_fts` | ✅ | Rebuilds FTS index, creates trace + audit |
| `cogito maintenance cleanup_traces` | ✅ | Purges old traces, creates trace + audit |
| `cogito migrate --db <path>` | ✅ | Overrides default DB path |
| `cogito chat --db <path>` | ✅ | Overrides default DB path |
| `cogito replay --db <path>` | ✅ | Overrides default DB path |
| `cogito maintenance --db <path>` | ✅ | Overrides default DB path |

## Test Results

| Check | Result |
|-------|--------|
| `pytest` | **320 passed** (306 previous + 14 added in Phase 7) |
| `ruff check src/` | All checks passed |
| `mypy src/` | Success: no issues found in 60 source files |

### Test Breakdown by Module

| Area | Tests | Status |
|------|-------|--------|
| api | 35 | ✅ |
| autonomy (gate, loop, scheduler) | 17 | ✅ |
| capability (registry, tools) | 19 | ✅ |
| cli (replay) | 6 | ✅ (new) |
| context | 4 | ✅ |
| e2e | 3 | ✅ |
| governance (audit, policy) | 16 | ✅ |
| mcp (client, manager, server) | 20 | ✅ |
| memory (candidates, retrieval, vector) | 25 | ✅ |
| models (adapter, openai, streaming) | 8 | ✅ |
| runtime (budget, drift, kernel, interrupt, pipeline, subagent) | 32 | ✅ |
| skill (manifest, runner, storage) | 19 | ✅ |
| storage (approval, artifacts, memory, messages, sessions, completeness, workspace) | 43 | ✅ |
| shared (events, manifests, policy, schedule, state, trace, calls, models) | 27 | ✅ |
| trace (lineage, redaction, replay, tracer) | 18 | ✅ |

## Database

- **Default path:** `~/.cogito/cogito.db` (auto-created)
- **Override:** `--db <path>` on any subcommand
- **Engine:** SQLite with WAL mode + foreign keys
- **Migrations:** standalone `0001_initial.sql` in `storage/migrations/`
- **Tables:** workspaces, sessions, messages, memories, memory_candidates, traces, spans, model_calls, tool_calls, audit_logs, approval_records, source_lineage, context_items, skill_pool, workspace_skills, skill_run_logs, workspace_settings, scheduled_jobs, notifications, interrupted_turns, schema_version, file_artifacts, memory_embeddings, memories_fts

## Known Limitations

### Functional
1. **MockModel only** — default provider `mock` echoes user input. Real model requires `--provider openai` with configured API key.
2. **No vector search by default** — `sentence-transformers` is optional; FTS5 is the primary MVP retrieval.
3. **// Experimental: /chat/stream** — bypasses RuntimeKernel, no trace/audit/policy. Marked with `X-Experimental: bypasses RuntimeKernel` header.
4. **Single-user** — no auth, no multi-tenant.
5. **CLI-only approval** — approval resume in API works via `POST /chat/resume` but inline approval prompt only works in CLI.

### Security
6. **Secrets in env** — API keys via `MODEL_API_KEY` env var; no encrypted secret store.
7. **Prompt injection** — UNTRUSTED_CONTENT wrapping applied to tool results, but no active adversarial guard.
8. **No shell execution** — policy explicitly denies `shell.execute`; no sandbox.

### Observability
9. **Trace redaction** — applies to prompt/response summaries in replay; full payloads not stored.
10. **Audit retention** — cleanup via `cogito maintenance cleanup_traces`; no auto-policy.

### Performance
11. **In-memory only for test** — CI uses `:memory:` DB; persistent DB for real use.
12. **No connection pooling** — single SQLite connection, not suitable for concurrent API access under load.

## Out of Scope for v0.1.0

The following MUST NOT be included in this release:

- ❌ Web UI / TUI / Dashboard
- ❌ Telegram / Discord / Feishu / WeChat channels
- ❌ Plugin marketplace or third-party skill install
- ❌ Multi-agent orchestration or multi-user
- ❌ Cloud sync or distributed queues
- ❌ Long-running daemon with auto-push notifications
- ❌ Shell execution or browser automation
- ❌ Email sending or calendar modification
- ❌ Proactive background skill execution (MVP freeze)

## Release Checklist

- [x] `pytest` — 320 passed
- [x] `ruff check src/` — clean
- [x] `mypy src/` — clean
- [x] `cogito migrate` creates `~/.cogito/cogito.db`
- [x] `cogito chat` displays trace_id + state
- [x] `cogito replay list` shows traces
- [x] `cogito replay show <id>` shows detail with redaction
- [x] `cogito maintenance usage` creates trace + audit
- [x] `--db` flag overrides default path
- [x] `/chat/stream` marked experimental
- [x] AGENTS.md, docs/07, README consistent
- [x] No governance/audit/trace bypass

## Next Steps (v0.2.0)

1. Multi-channel Gateway (CLI + API unification)
2. Real model provider config (Ollama / OpenAI)
3. Background daemon with controlled push
4. User data export UX
5. Skill pool marketplace (curated only)
6. Drift maintenance scheduling

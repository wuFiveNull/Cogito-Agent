# Cogito-Agent v0.1.0-alpha

## Code Baseline

- **Tag:** `v0.1.0-alpha`
- **Code baseline commit:** `d6961fe` (Phase 7: CLI/API polish, replay commands, drift maintenance)
- **Release readiness audit:** `05a0ca6` (doc sync 306→320, fresh checkout verification, release checklist)

## What's Included

- **Phase 1–7 / Epics A–S complete** — full turn pipeline, context engine, tool dispatch, approval flow, budget enforcement, trace/audit integration, policy matrix, memory lifecycle, path sandboxing, JSON Schema validation, storage completeness (hard delete, export, migration), skill runtime, background security, failure/retry, interrupt/resume, drift maintenance, CLI/API polish, replay
- **320 tests passing** — pytest, ruff, mypy all clean from fresh checkout

## CLI Commands

| Command | Description |
|---------|-------------|
| `cogito migrate` | Initialize database (default: `~/.cogito/cogito.db`) |
| `cogito chat` | Interactive chat session with trace_id + state display |
| `cogito replay list` | List recent traces |
| `cogito replay show <id>` | Inspect a trace (state path, model/tool calls, policy decisions) |
| `cogito maintenance usage` | Usage report (creates trace + audit log) |
| `cogito maintenance consolidate` | Deduplicate memories (creates trace + audit log) |
| `cogito maintenance archive` | Archive stale memories (creates trace + audit log) |
| `cogito maintenance refresh_fts` | Rebuild FTS index (creates trace + audit log) |
| `cogito maintenance cleanup_traces` | Purge old traces (creates trace + audit log) |

All commands accept `--db <path>` to override default database path.

## API Endpoints

- `POST /chat` — synchronous chat
- `POST /chat/stream` — **experimental** streaming (bypasses RuntimeKernel, marked with `X-Experimental` header)
- `POST /chat/resume` — resume after approval
- `POST /sessions` — create session
- `GET /traces/{id}` — inspect trace

## Database

- **Default:** `~/.cogito/cogito.db` (auto-created)
- **Override:** `--db <path>` on any subcommand
- **Engine:** SQLite with WAL mode + foreign keys
- **Tables:** 25+ tables covering workspaces, sessions, messages, memories, traces, spans, model/tool calls, audit logs, approvals, lineage, context, skills, schedules, notifications, interrupts, file artifacts, embeddings, FTS

## Known Limitations

1. **MockModel only** — default provider echoes user input; real model requires `--provider openai` with API key
2. **No vector search by default** — FTS5 is primary MVP retrieval; `sentence-transformers` is optional
3. **`/chat/stream` is experimental** — bypasses RuntimeKernel, no trace/audit/policy
4. **Single-user** — no auth, no multi-tenant
5. **CLI-only inline approval** — API resume works but approval prompt is CLI-only
6. **Secrets via env var** — no encrypted secret store
7. **No shell execution** — policy denies `shell.execute`; no sandbox
8. **No connection pooling** — single SQLite connection, not suitable for concurrent API load

## Out of Scope

- Web UI / TUI / Dashboard
- Telegram / Discord / Feishu / WeChat channels
- Plugin marketplace or third-party skill install
- Multi-agent orchestration or multi-user
- Cloud sync or distributed queues
- Long-running daemon with auto-push notifications
- Shell execution or browser automation
- Proactive background skill execution (MVP freeze)

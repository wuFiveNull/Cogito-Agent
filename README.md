# Cogito-Agent

Local-first personal Agent runtime with long-term memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Initialize database (default: ~/.cogito/cogito.db, use --db to override)
cogito migrate

# Configuration
cogito config show                                    # view current config
cogito config set model.provider mock                 # set provider (default: mock)
cogito doctor                                         # check system health

# Interactive chat (uses config model provider)
cogito chat

# Memory management
cogito memory list                                    # list memories
cogito memory search <query>                          # search memories
cogito memory review                                  # review pending candidates
cogito memory edit <id> --text "..."                  # edit a memory
cogito memory pin <id>                                # pin a memory
cogito memory merge <src> <tgt>                       # merge memories
cogito memory embeddings status                       # embedding provider/index status
cogito memory embeddings doctor                       # check embedding health
cogito memory embeddings rebuild --workspace default  # rebuild embeddings
cogito memory embeddings retry-failed --workspace default  # retry failed embeddings
cogito memory search <query> --explain                # detailed score breakdown

# Skill management & approval workflow
cogito skill list                                     # list installed skills
cogito skill validate <file>                          # validate skill manifest
cogito skill run <name>                               # run a skill
cogito approval list                                  # list pending approvals
cogito approval show <id>                             # show approval details
cogito approval approve <id>                          # approve a pending request
cogito approval reject <id>                           # reject a pending request
cogito approval resume <skill_run_id>                 # resume after approval decision

# Observability
cogito traces list                                    # list traces with filtering
cogito traces show <trace_id>                         # show trace detail
cogito audit list                                     # list audit logs
cogito audit show <audit_id>                          # show audit log detail
cogito usage --last 7d                                # usage summary
cogito replay list                                    # list replayable traces
cogito replay show <trace_id>                         # show full replay detail

# Export / Backup
cogito export data --workspace default --out export.json    # workspace data export
cogito export memories --out memories.json                  # memory JSON export
cogito export traces --out traces.json                      # trace JSON export
cogito backup create --out backup.zip                       # full system backup
cogito backup restore backup.zip --dry-run                  # preflight validation
cogito backup restore backup.zip                            # restore from backup
# NOTE: secrets are excluded from backup by default; use --include-secrets

# Daemon / Scheduled maintenance
cogito daemon once                                    # run one tick cycle
cogito daemon status                                  # check daemon status
cogito schedule list                                  # list scheduled jobs
cogito schedule maintenance consolidate --daily 03:00 # schedule a task

# Autonomy notifications (v0.7)
cogito autonomy emit --title "test" --body "hello"    # emit an autonomy event
cogito autonomy decisions                              # list notification decisions
cogito autonomy outbox                                 # list outbox messages
cogito autonomy feedback <id> --value useful           # record feedback on a decision

# Inbox
cogito inbox list                                     # list inbox items
cogito inbox read <id>                                # show inbox item detail

# Provider management (v0.6)
cogito provider list                                  # list registered providers
cogito provider show <name>                           # show provider details
cogito provider doctor                                # check current provider config
cogito provider test <name>                           # test provider (add --live for network)

# Secrets management (v0.6)
cogito secrets list                                   # list secrets (metadata only)
cogito secrets show <name>                            # show secret metadata (never value)
cogito secrets set <name>                             # set secret (from prompt or --value)
cogito secrets delete <name>                          # delete a secret (writes audit)
cogito secrets rotate <name>                          # rotate secret value (writes audit)
cogito secrets test <name>                            # test secret availability

# API authentication (single-key, optional)
export COGITO_API_KEY=your-secret-key
cogito-demo              # start API server with Bearer token auth

# True per-token streaming: /chat/stream
# Uses RuntimeKernel.process_stream() with SSE delta events per token
# Adapter supports_streaming=True → true per-token streaming
# Adapter supports_streaming=False → full response emitted as single delta
# SSE events: metadata (trace_id, session_id, workspace_id, channel, request_id),
#             delta (one per token), final, error, approval_required,
#             tool_call_started, tool_call_completed
# Redaction applied per-delta and on final/error/approval events
# Trace/replay/audit full-chain available from trace_id in metadata
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "hello", "session_id": "...", "workspace_id": "..."}'
```

**Notes:**
- **Default DB:** `~/.cogito/cogito.db` — use `--db <path>` to override.
- **MockModel** is the default provider. For a real model, set `model.provider` via `cogito config` and configure the API key through an environment variable (never written to config file, trace, audit, or export).
- **API auth:** Set `COGITO_API_KEY` to enable single-key Bearer token authentication on all endpoints, including `/docs` and `/openapi.json`. When unset, all endpoints are accessible without auth.
- This is a **single-user, single-key** auth scheme — not OAuth/RBAC.
- **Secret backends:** Default is `DevSqliteSecretProvider` (plaintext SQLite, dev only). For production, use `cogito config set secrets.backend local_encrypted` (requires `pip install cryptography`) or `cogito config set secrets.backend keychain` (OS keychain via `keyring` library). See `cogito doctor` for security risk assessment.
- **Limitations:** No multi-user / OAuth / RBAC. No config editing (read-only). No real Telegram / Feishu delivery (outbox is local SQLite queue). No advanced diagnostics or diagnostic bundle export. No Plugin Marketplace. No cloud sync or distributed queue. `cogito daemon run` is blocking (no background process management). No LLM relevance judge for autonomy decisions (deterministic rules only). Session title editing not yet available in the UI.
- **/chat/stream** uses true per-token streaming when the model adapter supports it (`supports_streaming=True` and `stream_chat()`). Falls back to single-delta emission for non-streaming adapters.
- Streaming tool calls (v0.10): `process_stream()` now yields `tool_call_started` and `tool_call_completed` SSE events during tool dispatch, with full governance pipeline (policy, approval, audit, trace, redaction). Tools are dispatched in a multi-round loop up to `max_tool_rounds` (default 3).

## Requirements

- Python 3.12+

## Release Status

**v0.16.0-dev (BGE-M3 Embedding + Memory Retrieval V2)** — Memory Retrieval V2 with OpenAI-compatible embedding API (BAAI/bge-m3, 1024-dim), dual independent dense/sparse recall, Retrieval Gate, QueryBuilder, CandidateFusion with score breakdown, resident memory layer, type threshold/quota, MemoryEmbeddingIndexService, retry-failed/purge-stale, RetrievalTrace persistence, CLI embed doctor/rebuild, API `/memories/embeddings/status` etc.
Verified baseline: **1433+ tests passed, 4 skipped** under Python 3.11; Python 3.12/3.13 hosted release verification remains required.
Includes: v0.14.0 Real Skills + Drift Runtime, v0.13.0 Workspace Files + Artifacts, v0.11.0 Delivery Hardening, v0.10.0 Hybrid Memory + Streaming Tools + Tool Loop, v0.9.0 Multi-Session Chat, v0.8.0 Console MVP, v0.7.0 Autonomy Plane MVP.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```

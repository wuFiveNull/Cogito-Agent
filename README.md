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

# Export
cogito export --workspace default --out export.json

# Daemon / Scheduled maintenance
cogito daemon once                                    # run one tick cycle
cogito daemon status                                  # check daemon status
cogito schedule list                                  # list scheduled jobs
cogito schedule maintenance consolidate --daily 03:00 # schedule a task

# Inbox
cogito inbox list                                     # list inbox items
cogito inbox read <id>                                # show inbox item detail

# API authentication (single-key, optional)
export COGITO_API_KEY=your-secret-key
cogito-demo              # start API server with Bearer token auth

# Streaming: /chat/stream (RuntimeKernel-backed)
# POST /chat/stream — SSE streaming via RuntimeKernel (governance/trace/audit/redaction)
# Responses use SSE events: metadata, final, approval_required, error
# Exposes trace_id in metadata and final events for replay
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "hello", "session_id": "...", "workspace_id": "..."}'
```

**Notes:**
- **Default DB:** `~/.cogito/cogito.db` — use `--db <path>` to override.
- **MockModel** is the default provider. For a real model, set `model.provider` via `cogito config` and configure the API key through an environment variable (never written to config file, trace, audit, or export).
- **API auth:** Set `COGITO_API_KEY` to enable single-key Bearer token authentication on all endpoints, including `/docs` and `/openapi.json`. When unset, all endpoints are accessible without auth.
- This is a **single-user, single-key** auth scheme — not OAuth/RBAC.
- **Limitations:** No Web UI or TUI, no encrypted secret store. `cogito daemon run` is blocking (no background process management). Export is workspace-scoped only.
- **/chat/stream**: Uses chunked final response (not true per-token streaming). RuntimeKernel executes fully before emitting SSE events. Future versions may add true token streaming with tool-interrupt support.

## Requirements

- Python 3.12+

## Release Status

**v0.4.0-dev (streaming runtime integration)** — Not released. No GitHub tag or release.
Verified: **616 tests passing**, `ruff check src/` clean, `mypy src/` clean (64 files).
/chat/stream fully integrated with RuntimeKernel. Dogfood validation passed (70/70 checks).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```

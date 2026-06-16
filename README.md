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

# Observability
cogito traces list                                    # list traces with filtering
cogito traces show <trace_id>                         # show trace detail
cogito audit list                                     # list audit logs
cogito audit show <audit_id>                          # show audit log detail
cogito usage summary --last 7d                        # usage summary

# Export
cogito export --workspace default --out export.json

# Daemon / Scheduled maintenance
cogito daemon once                                    # run one tick cycle
cogito daemon status                                  # check daemon status
cogito schedule list                                  # list scheduled jobs
cogito schedule maintenance consolidate --daily 03:00 # schedule a task

# API authentication (single-key, optional)
export COGITO_API_KEY=your-secret-key
cogito-demo              # start API server with Bearer token auth
```

**Notes:**
- **Default DB:** `~/.cogito/cogito.db` — use `--db <path>` to override.
- **MockModel** is the default provider. For a real model, set `model.provider` via `cogito config` and configure the API key through an environment variable (never written to config file, trace, audit, or export).
- **API auth:** Set `COGITO_API_KEY` to enable single-key Bearer token authentication on all endpoints, including `/docs` and `/openapi.json`. When unset, all endpoints are accessible without auth.
- This is a **single-user, single-key** auth scheme — not OAuth/RBAC.
- **Limitations:** No Web UI or TUI, no rate limiting, no encrypted secret store. `cogito daemon run` is blocking (no background process management). Export is workspace-scoped only.

## Requirements

- Python 3.12+

## Release Status

**v0.2.0-alpha** — Verified: **364 tests passing**, `ruff check src/` clean, `mypy src/` clean (62 files).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```

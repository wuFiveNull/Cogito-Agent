# 10 V0.2.0-alpha Release Readiness

## Release Candidate

**v0.2.0-alpha** — 2f3a3ec

## Verification Environment

| Item | Detail |
|------|--------|
| OS | Windows |
| Python | 3.12.13 |
| Package | cogito-agent 0.2.0-alpha |
| pip install | `pip install -e ".[dev]"` |

## Test Results

### pytest (364 passed, 0 failed)

```
collected 364 items
... (all passed)
```

### ruff check src/ — clean

```
All checks passed!
```

### mypy src/ — clean (62 files)

```
Success: no issues found in 62 source files
```

## Verified CLI Commands

| Command | Status |
|---------|--------|
| `cogito config show` | Verified (12 tests) |
| `cogito config set <key> <value>` | Verified |
| `cogito doctor` | Verified |
| `cogito export --workspace default --out export.json` | Verified (8 tests) |
| `cogito daemon once` | Verified |
| `cogito daemon status` | Verified |
| `cogito schedule list` | Verified (6 tests) |
| `cogito schedule maintenance consolidate --daily 03:00` | Verified |
| `cogito traces list [--workspace --status --days]` | Verified (9 tests) |
| `cogito traces show <id>` | Verified |
| `cogito audit list [--workspace]` | Verified |
| `cogito audit show <id>` | Verified |
| `cogito usage summary --last 7d` | Verified |

## Verified API Auth

| Scenario | Status |
|----------|--------|
| `COGITO_API_KEY` not set → all endpoints accessible | Verified |
| Auth enabled, no `Authorization` header → 401 | Verified |
| Auth enabled, wrong Bearer token → 401 | Verified |
| Auth enabled, correct Bearer token → 200/404 | Verified |
| Auth enabled, `/docs` and `/openapi.json` protected → 401 | Verified |
| Auth disabled, `/docs` and `/openapi.json` accessible | Verified |

## Verified Model Config Behavior

| Scenario | Status |
|----------|--------|
| CLI chat uses `~/.cogito/config.json` provider | Verified |
| API chat uses shared `build_model_adapter_from_config()` helper | Verified |
| `model.provider = mock` → kernel uses echo (no real model) | Verified |
| Model adapter only created for non-mock providers | Verified |
| API key read from env var only (never persisted in config) | Verified |
| CLI and API use same config loading path | Verified |

## Known Limitations

1. **MockModel still default** — `config set model.provider mock` is default; real model requires env var key
2. **API auth is single-key only** — no user management, no scopes, no rate limiting, no OAuth/RBAC; `/docs` and `/openapi.json` are also protected when auth enabled
3. **Export is workspace-scoped only** — no full-database export
4. **Daemon is blocking** — `cogito daemon run` blocks terminal; no background process management
5. **Schedule maintenance uses one_shot fallback** — if neither `--daily` nor `--weekly` given, runs once immediately
6. **Usage summary is time-window only** — no per-workspace breakdown, no trend visualization
7. **Audit log show is raw SQL dump** — no redaction on audit log values (audit logs should not contain secrets)
8. **No encrypted secret store** — API keys stored only in env vars
9. **No rate limiting** — single-user tool, no abuse protection
10. **No Web UI or TUI** — CLI-only and REST API

## Tag Recommendation

**Yes** — suggested tag: `v0.2.0-alpha` at commit `2f3a3ec`.

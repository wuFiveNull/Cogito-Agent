# Repository Guidelines

## State of the Repo

All V1 MVP epics (1–14), V2 items, and Architecture Completion Plan Phase 1–4 (Epics A–J) are complete. Working on Phase 5.

## Architecture Completion Status (docs/07_ARCHITECTURE_COMPLETION_PLAN.md)

- ✅ Phase 1 (Epics A–B): Runtime full turn pipeline, context engine with budget shares
- ✅ Phase 2 (Epics C–E): Tool dispatch, approval flow, budget enforcement
- ✅ Phase 3 (Epics F–G): Trace/audit integration, policy matrix (call_model/tool/trace_log)
- ✅ Phase 4 (Epics H–J): Candidate extraction, memory ranking, memory versioning, token_count utility
- ❌ Phase 5 (Epics K–L): Capability safety (path sandboxing, JSON Schema), storage completeness (hard delete, export, migration)
- ❌ Phase 6 (Epics M–P): CLI polish, config files, context ranking/trimming
- ❌ Phase 7 (Epics Q–S): Error handling, documentation, E2E tests

## V2 Status

- ✅ All V2 items except cloud migration adapters (deprioritized)
- ✅ 251 tests passing, ruff clean, mypy clean

## Project Purpose

Local-first personal Agent runtime with long-term memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior.

## Implementation Order (Epic sequence from backlog)

1. Bootstrap (package, ruff, mypy, pytest config)
2. Shared types/schemas (RuntimeEvent, turn state, manifests)
3. Storage layer (SQLite, repositories, workspace filtering)
4. Trace & audit (spans, model/tool call logs, redaction)
5. Runtime kernel (state machine, turn lifecycle, budget)
6. Policy engine (static matrix, approval, deny)
7. Capability registry (manifest loader, validation, safe tools)
8. Memory & context (FTS5 retrieval, candidates, ranking)
9. CLI chat loop (session, inline approval, display)
10. API chat endpoint (FastAPI, after CLI is stable)
11. Model provider adapter (OpenAI-compatible or Ollama)
12. E2E local demo
13–14. Skill & autonomy (V1, after MVP)

Each epic depends on previous ones. Do not skip ahead.

## Forbidden Dependencies

- `runtime` must not import concrete model providers, tool implementations, storage drivers, or UI channels.
- `capability` must not bypass `governance` (policy/approval).
- `memory` must not directly call models.
- `api` must not write storage except through application services.

## Package Boundaries

```
src/cogito_agent/
  runtime/     — turn lifecycle, state machine, orchestration
  models/      — provider-neutral model interface
  storage/     — tables, repositories, migrations
  memory/      — memory entities, lifecycle, retrieval
  context/     — context ranking, trimming, lineage
  capability/  — manifests, registry, invocation interface
  governance/  — policy, approvals, audit decisions
  trace/       — trace/span/model/tool logs
  cli/         — channel adapter (CLI)
  api/         — channel adapter (FastAPI)
tests/
docs/
```

## Private Directories

Do not read, modify, or reference `docs_zh/`, `private/`, `.local/`, or `secrets/` unless the user explicitly asks.

## What Not to Overbuild (MVP)

No cloud sync, plugin marketplaces, distributed queues, multi-agent orchestration, UI clients (TUI/Web), proactive notifications, background skill execution, scheduler, or MCP integration.

## Tech Stack

- Python 3.12+, Pydantic, SQLite (no ORM unless schema grows complex)
- pytest, Ruff, mypy
- FastAPI only after CLI MVP is stable
- SQLite FTS5 for MVP retrieval (no vector yet)

## Testing Expectations

Add tests with each behavioral change. Security/approval/audit/deletion paths require negative tests. New public functions should be typed.

## If Docs Conflict

Lower-numbered spec wins for product scope; more specific spec wins for implementation details. Chinese architecture doc is reference material, not an implementation contract.

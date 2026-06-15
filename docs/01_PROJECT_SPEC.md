# 01 Project Spec

## Identity

| Field | Value |
|---|---|
| Project name | Cogito-Agent |
| Description | A local-first personal Agent runtime with memory, governed capabilities, traceable execution, reusable skills, and constrained proactive behavior. |
| Core goal | Help one user run repeatable agent workflows safely over long-lived personal context. |
| Target user | A technical individual who wants a local personal assistant for coding, research, planning, and information management. |

## Main Use Cases

- Chat through a CLI or API endpoint with persistent sessions.
- Retrieve relevant project/user memory into model context.
- Call approved local tools through a capability registry.
- Record trace, audit, model calls, tool calls, and source lineage.
- Extract memory candidates from completed turns for review.
- Later: run skills and limited proactive/background tasks.

## Non-Goals

- Multi-tenant SaaS.
- Full desktop or web UI in MVP.
- Autonomous external message sending in MVP.
- Marketplace plugin installation in MVP.
- Distributed execution, cloud sync, or high-availability storage in MVP.

## Principles

Local-first: store state, memory, traces, files, and configuration locally by default. Any future remote provider must be replaceable and explicitly configured.

Security-first: every capability invocation is evaluated as `Actor + Capability + Resource + Operation + Context -> Decision`; write, send, delete, and execute operations are audited and may require approval.

## Scope

| Phase | Scope |
|---|---|
| MVP | Python package, SQLite storage, CLI chat loop, single model provider adapter, runtime state machine, policy MVP, capability registry, trace/audit logs, basic memory/context retrieval, local demo. |
| V1 | HTTP API, skill runtime, workspace skill copies, richer memory review/correction, BM25/vector retrieval, approval persistence, export/delete flows. |
| V2 | Proactive loop, scheduler, Drift runtime, multiple workspaces, plugin/MCP integration, subagents, cloud migration adapters. |

## Recommended Technical Stack

- Language: Python 3.12+.
- API: FastAPI after CLI MVP is stable.
- Storage: SQLite for MVP; SQLAlchemy or SQLModel if schema complexity grows.
- Validation: Pydantic models for runtime events, manifests, policy inputs, and logs.
- Tests: pytest.
- Quality: Ruff and mypy.
- Retrieval: SQLite FTS5 for MVP; vector index later.

## Repository Structure

```text
src/cogito_agent/
  runtime/
  models/
  storage/
  memory/
  context/
  capability/
  governance/
  trace/
  cli/
  api/
tests/
docs/
```

## Package Boundaries

| Package | Owns | Must not own |
|---|---|---|
| `runtime` | Turn lifecycle, state machine, orchestration | Provider SDKs, concrete tool code, SQL details |
| `models` | Provider-neutral model interface | Policy or storage decisions |
| `storage` | Tables, repositories, migrations | Runtime branching logic |
| `memory` | Memory entities, lifecycle, retrieval | Prompt assembly policy |
| `context` | Context ranking, trimming, lineage | Long-term storage persistence |
| `capability` | Manifests, registry, invocation interface | Approval decisions |
| `governance` | Policy, approvals, audit decisions | Tool execution |
| `trace` | Trace/span/model/tool logs | Business policy |
| `cli`/`api` | Channel adapters | Runtime internals |

Forbidden dependencies: `runtime` must call abstract interfaces, not concrete providers; `capability` must not bypass `governance`; `memory` must not directly call models; `api` must not write storage except through application services.

## Assumptions

- MVP is single-user and local.
- Python is acceptable for initial implementation.
- Model credentials are supplied through local environment/config and never stored in git.
- The existing root architecture document remains reference material, not an implementation contract.

## Open Questions

- Which model provider is first: OpenAI-compatible HTTP, local Ollama, or both?
- Should memory acceptance be manual in MVP or logged as pending only?
- Should SQLite migrations use Alembic immediately or a simple schema initializer first?
- What local file sandbox should capability tools enforce?

# 06 Implementation Backlog

## Epic 1: Project Bootstrap

Goal: create a minimal Python package and developer workflow.
Scope: package layout, dependency config, test config, lint/type config.
Files likely affected: `pyproject.toml`, `src/cogito_agent/`, `tests/`.
Dependencies: none.
Acceptance criteria: package imports, `pytest` runs, Ruff/mypy commands are documented.
Out of scope: runtime behavior.

## Epic 2: Shared Types and Schemas

Goal: define provider-neutral data contracts.
Scope: RuntimeEvent, turn state, capability manifest, policy request/decision, trace/span models.
Files likely affected: `src/cogito_agent/shared/`, `src/cogito_agent/runtime/`.
Dependencies: Epic 1.
Acceptance criteria: schemas validate good/bad fixtures.
Out of scope: persistence and execution.

## Epic 3: Storage Layer

Goal: persist sessions, messages, memory, trace, audit, and calls locally.
Scope: SQLite schema initializer, repositories, workspace filtering, soft delete.
Files likely affected: `src/cogito_agent/storage/`, `tests/storage/`.
Dependencies: Epic 2.
Acceptance criteria: CRUD tests pass; all user data queries require `workspace_id`.
Out of scope: vector search.

## Epic 4: Trace and Audit MVP

Goal: make execution observable from the first demo.
Scope: trace/span creation, model/tool logs, audit rows, redaction helper.
Files likely affected: `src/cogito_agent/trace/`, `src/cogito_agent/governance/`.
Dependencies: Epic 3.
Acceptance criteria: a test turn creates trace, spans, audit records, and redacted summaries.
Out of scope: deterministic replay.

## Epic 5: Runtime Kernel MVP

Goal: implement the turn lifecycle and state machine.
Scope: event ingestion, state transitions, budget checks, result composition, failure handling.
Files likely affected: `src/cogito_agent/runtime/`.
Dependencies: Epics 2-4.
Acceptance criteria: transition tests cover valid/invalid paths; a simple turn completes.
Out of scope: background execution.

## Epic 6: Policy Engine MVP

Goal: enforce static capability decisions.
Scope: policy matrix, approval request model, deny/allow/audit behavior.
Files likely affected: `src/cogito_agent/governance/`.
Dependencies: Epics 2 and 4.
Acceptance criteria: tests cover allow, allow_with_audit, require_approval, deny, escalate.
Out of scope: policy DSL and grants.

## Epic 7: Capability Registry MVP

Goal: register and invoke safe local tools through manifests.
Scope: manifest loader, schema validation, result normalization, one or two safe tools.
Files likely affected: `src/cogito_agent/capability/`.
Dependencies: Epics 4-6.
Acceptance criteria: invalid manifests fail; tool calls pass through policy and trace.
Out of scope: MCP, plugins, shell execution.

## Epic 8: Memory and Context MVP

Goal: retrieve useful local context and propose memory candidates.
Scope: memory tables, candidate extraction, accepted-memory retrieval, context ranking/trimming.
Files likely affected: `src/cogito_agent/memory/`, `src/cogito_agent/context/`.
Dependencies: Epics 3-5.
Acceptance criteria: accepted memories can be retrieved; candidates are linked to source messages.
Out of scope: embeddings and automatic consolidation.

## Epic 9: CLI Chat Loop

Goal: provide a runnable local interaction path.
Scope: CLI command, session creation, inline approval prompts, turn display.
Files likely affected: `src/cogito_agent/cli/`.
Dependencies: Epics 5-8.
Acceptance criteria: user can chat locally and inspect persisted messages/traces.
Out of scope: TUI, web UI, streaming.

## Epic 10: API Chat Endpoint

Goal: expose the runtime through HTTP after CLI works.
Scope: FastAPI app, chat endpoint, session endpoint, approval resume endpoint.
Files likely affected: `src/cogito_agent/api/`.
Dependencies: Epic 9.
Acceptance criteria: API tests create a turn and resume approval.
Out of scope: auth beyond local/dev token.

## Epic 11: Model Provider Adapter

Goal: connect runtime to one real model provider.
Scope: provider-neutral interface, OpenAI-compatible or local provider implementation, usage logging.
Files likely affected: `src/cogito_agent/models/`.
Dependencies: Epics 4 and 5.
Acceptance criteria: adapter returns normalized message/tool intent and logs usage.
Out of scope: multi-provider routing.

## Epic 12: End-to-End Local Demo

Goal: prove MVP works from a fresh checkout.
Scope: seed config, demo script/docs, one safe tool, one memory, one chat.
Files likely affected: `docs/`, `src/cogito_agent/cli/`, `tests/e2e/`.
Dependencies: Epics 1-11.
Acceptance criteria: documented command runs a complete local turn with trace/audit output.
Out of scope: production deployment.

## Epic 13: Skill Runtime V1

Goal: execute approved interactive skills.
Scope: skill manifest, workspace copy, step runner, step traces, permission preflight, run history.
Files likely affected: `src/cogito_agent/skill/`, `src/cogito_agent/capability/`.
Dependencies: Epic 12.
Acceptance criteria: one sample skill runs interactively and logs step spans.
Out of scope: background skills and marketplace import.

## Epic 14: Autonomy V1

Goal: introduce controlled background behavior.
Scope: scheduler model, quiet hours, notification gate, deduplication, feedback records.
Files likely affected: `src/cogito_agent/autonomy/`, `src/cogito_agent/governance/`.
Dependencies: Epic 13.
Acceptance criteria: scheduled dry-run job creates trace/audit and respects quiet hours.
Out of scope: external push channels and fully autonomous action.

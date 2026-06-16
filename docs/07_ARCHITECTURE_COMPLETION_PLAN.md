# 07 Architecture Completion Plan

## Goal

Bridge all gaps between the current implementation and the full architecture design described in `docs_zh/` (Chinese architecture docs).

## Priority Legend

- **P0** — Core pipeline; must work for any feature to function correctly
- **P1** — Blocks user-facing functionality (approval, tools, memory)
- **P2** — Important for production quality (logging, audit, security)
- **P3** — Nice-to-have completeness (versioning, replay, maintenance)

---

## Phase 1: Core Pipeline (P0)

### Epic A — Runtime Kernel Full Turn Pipeline

Rewrite `RuntimeKernel.process()` to implement the actual 9-step turn lifecycle per `02_RUNTIME_SPEC.md:56-64`:

1. **Receive event** — already done
2. **Create trace** — already done
3. **Load session** — already done
4. **Build context** — use `ContextEngine.build()` with memories + recent messages
5. **Policy check model call** — before model call, evaluate `PolicyEngine`
6. **Model call** — call adapter, capture tool_intents
7. **Tool dispatch loop** — iterate tool_intents: resolve capability → policy → approval → execute → log → feed result back to model
8. **Compose result** — build structured `TurnResult` with text + tool summaries + citations + approval status
9. **Persist + extract** — save trace/audit/lineage, extract memory candidates

**Files:** `runtime/kernel.py`, `runtime/budget.py`
**Tests:** `tests/runtime/test_kernel.py`
**Dependencies:** ContextEngine must be ready (Epic B), PolicyEngine integration (part of this epic)

### Epic B — Context Engine Pipeline

1. Wire `ContextEngine.build()` into `RuntimeKernel._load_context()`
2. Implement `_apply_budget_shares()` — proportional token allocation per category
3. Accept all context sources: recent messages, accepted memories, tool results, file artifacts, system policy text
4. Implement accurate token estimation (support tiktoken if available)

**Files:** `context/engine.py`, `runtime/kernel.py`
**Tests:** `tests/context/test_engine.py`

---

## Phase 2: Tool Execution & Governance (P1)

### Epic C — Tool Call Flow

1. After model returns `tool_intents`, iterate and dispatch:
   - Resolve each intent via `CapabilityRegistry`
   - Build `PolicyRequest` and evaluate via `PolicyEngine`
   - If `deny` → record and surface error
   - If `require_approval` → create approval record, park turn in `awaiting_approval`
   - If `allow` → `CapabilityRegistry.invoke()`
2. Feed tool results back to model for follow-up response
3. Support multi-round tool loop within a single turn

**Files:** `runtime/kernel.py`, `runtime/approval.py`
**Tests:** `tests/runtime/test_kernel.py`

### Epic D — Approval Flow

1. When policy returns `require_approval`, persist to `approval_records` table and transition state to `awaiting_approval`
2. CLI: prompt user inline with capability/operation/resource/risk info
3. API: add `POST /chat/resume` endpoint to resume after approval
4. On approval result event, re-evaluate policy (may have changed) and continue execution

**Files:** `runtime/kernel.py`, `cli/chat.py`, `api/app.py`
**Tests:** `tests/runtime/test_kernel.py`, `tests/api/test_api.py`

### Epic E — Budget Enforcement

1. Check `TurnBudget.can_call_model()` before model calls
2. Check `TurnBudget.can_call_tool()` before tool calls
3. Enforce wall-clock timeout
4. Surface budget exceeded as `TurnResult` error (not crash)

**Files:** `runtime/budget.py`, `runtime/kernel.py`
**Tests:** `tests/runtime/test_budget.py`

---

## Phase 3: Observability & Audit (P1)

### Epic F — Trace/Audit/Logging Integration

1. After model call → `Tracer.log_model_call()` with all metadata
2. After tool call → `Tracer.log_tool_call()` with decision/result
3. Audit all operations: tool calls, file reads, approvals, denials, memory changes, policy escalations
4. Populate span `input_summary`/`output_summary`
5. Record `SourceLineage` entries for context items used in response

**Files:** `runtime/kernel.py`, `skill/runner.py`
**Tests:** `tests/runtime/test_kernel.py`, `tests/trace/test_tracer.py`

### Epic G — Policy Engine Integration

1. Add missing policy rule: `system write trace log -> allow_with_audit`
2. Evaluate policy before each model call and capability invocation in kernel
3. Context-based policy differentiation (background vs interactive)
4. Add `risk_level` and `expected_side_effects` to approval records

**Files:** `governance/policy.py`, `runtime/kernel.py`, `storage/repositories.py`
**Tests:** `tests/governance/test_policy.py`

---

## Phase 4: Memory & Context Deepening (P2)

### Epic H — Memory Candidate Pipeline

1. After turn completes, call `CandidateExtractor.extract()` with assistant output
2. Store extracted candidates to `memory_candidates` table
3. Implement basic extraction heuristic (key statements, preference expressions, task declarations)

**Files:** `memory/candidates.py`, `runtime/kernel.py`
**Tests:** `tests/memory/test_candidates.py`

### Epic I — Memory Ranking & Lifecycle

1. Implement weighted ranking for memory search: `type_priority * recency_decay * confidence * keyword_boost * source_reliability`
2. Add `consolidated`/`indexed`/`stale` status transitions
3. Memory correction versioning: save old version as `stale` on update

**Files:** `memory/retrieval.py`, `storage/repositories.py`
**Tests:** `tests/memory/test_retrieval.py`

### Epic J — Context Engine Budget Allocation

1. Implement proportional token budget allocation per `BUDGET_SHARES`
2. Accurate token estimation (heuristic or tiktoken)
3. Keep source lineage for excluded-but-ranked context items

**Files:** `context/engine.py`
**Tests:** `tests/context/test_engine.py`

---

## Phase 5: Security & Correctness (P2)

### Epic K — Capability Safety

1. File path sandboxing: restrict `_read_file()` to workspace directory or configured root
2. Input validation against `CapabilityManifest.input_schema` (JSON Schema) before invoke
3. Full `ToolResult` schema: add `artifacts`, `redactions`, `lineage` fields

**Files:** `capability/registry.py`, `capability/tools.py`
**Tests:** `tests/capability/test_tools.py`, `tests/capability/test_registry.py`

### Epic L — Storage Completeness

1. Hard delete for sessions, messages, workspaces
2. Full data export: include memory candidates, file artifacts, audit logs, source lineage
3. Schema migration system

**Files:** `storage/repositories.py`, `cli/chat.py`, `api/app.py`, `storage/database.py`
**Tests:** `tests/storage/`

---

## Phase 6: Skill & Autonomy Depth (P2)

### Epic M — Skill Runtime

1. Rollback compensation: execute `manifest.rollback` steps in reverse order on failure
2. Permission preflight: compute union of all step permissions upfront
3. Output normalization: structured summary + artifacts + lineage
4. Semver enforcement: re-approval on major version change

**Files:** `skill/runner.py`, `skill/manifest.py`
**Tests:** `tests/skill/test_runner.py`

### Epic N — Background Security

1. Stricter policy rules for `context=background`
2. Background tasks must not access secrets, delete data, run shell, etc.
3. Audit all background task actions

**Files:** `governance/policy.py`, `autonomy/loop.py`
**Tests:** `tests/governance/test_policy.py`

---

## Phase 7: Resilience & Maintenance (P3)

### Epic O — Failure & Retry

Status: ✅ Complete (Phase 6)

1. Retry transient model/provider/tool failures (max 2, exponential backoff)
2. Check `idempotent` flag on `CapabilityManifest` before retry
3. Integrate `retrying` state transitions

**Files:** `runtime/kernel.py`
**Tests:** `tests/runtime/test_kernel.py`

### Epic P — Interrupt & Resume

Status: ✅ Complete (Phase 6)

1. Persist interrupted turn state
2. Resume: re-validate policy and budget
3. Support `interrupted`/`resuming` state transitions

**Files:** `runtime/kernel.py`, `storage/repositories.py`
**Tests:** `tests/runtime/test_kernel.py`

### Epic Q — Drift Maintenance Tasks

Status: ✅ Complete

1. Memory consolidation (deduplicate)
2. Stale memory detection and archival
3. FTS/index refresh
4. Trace cleanup
5. Usage reports

**Files:** `runtime/drift.py`
**Tests:** `tests/runtime/test_drift.py`

### Epic R — CLI & API Polish

Status: ✅ Complete

1. CLI inline tool approval prompt
2. CLI rich turn display (tool summaries, citations, approval status, trace_id, state)
3. API approval resume endpoint
4. API chat endpoint with model adapter
5. Default DB path is ~/.cogito/cogito.db (persistent)
6. /chat/stream marked experimental with X-Experimental header

**Files:** `cli/chat.py`, `cli/__init__.py`, `api/app.py`
**Tests:** `tests/cli/test_replay_cli.py`, `tests/api/test_api.py`

### Epic S — Replay

Status: ✅ Complete

1. Read-only trace inspector
2. Reconstruct state transitions, policy decisions, model/tool summaries, source lineage
3. CLI commands: `cogito replay list`, `cogito replay show <trace_id>`
4. Redacted output for sensitive fields

**Files:** `cli/replay.py`, `cli/__init__.py`
**Tests:** `tests/cli/test_replay_cli.py`, `tests/trace/test_replay.py`

---

## Dependency Graph

```
Phase 1 ──────────────────────────┐
  Epic A (Kernel Pipeline) ◄──────┤
  Epic B (Context Engine) ◄───────┤
                                   │
Phase 2 ──────────────────────────┤
  Epic C (Tool Call Flow) ◄───────┤── Depends on A
  Epic D (Approval Flow) ◄────────┤── Depends on A, C
  Epic E (Budget) ◄───────────────┤── Depends on A
                                   │
Phase 3 ──────────────────────────┤
  Epic F (Trace/Audit) ◄──────────┤── Depends on A, C
  Epic G (Policy Integration) ◄───┤── Depends on A
                                   │
Phase 4 ──────────────────────────┤
  Epic H (Memory Candidates) ◄────┤── Depends on A
  Epic I (Memory Ranking) ◄───────┤── Depends on H
  Epic J (Context Budget) ◄───────┤── Depends on B
                                   │
Phase 5 ──────────────────────────┤
  Epic K (Capability Safety) ◄────┤── Independent
  Epic L (Storage Completeness) ◄─┤── Independent
                                   │
Phase 6 ──────────────────────────┤
  Epic M (Skill Depth) ◄──────────┤── Depends on K
  Epic N (Background Security) ◄──┤── Depends on G
                                   │
Phase 7 ──────────────────────────┤
  Epic O (Retry) ◄────────────────┤── Depends on A
  Epic P (Interrupt/Resume) ◄─────┤── Depends on A
  Epic Q (Drift Maintenance) ◄────┤── Independent
  Epic R (CLI/API Polish) ◄───────┤── Depends on D, F
  Epic S (Replay) ◄───────────────┤── Depends on F
```

## Current Test Count

**320 tests** across all modules. All epics A–S are complete.

## Execution Strategy

1. Implement Phase 1 first — this rewrites the core turn pipeline and unblocks everything downstream
2. Each epic should be implemented as a single coherent change with corresponding tests
3. Run full test suite + ruff + mypy after each epic
4. Commit and push after each epic

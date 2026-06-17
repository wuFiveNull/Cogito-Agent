# Architecture Requirements Gap Review

Based on the Cogito-Agent architecture design document, this document provides a gap assessment for each major module.

---

## 1. User Entry Layer

| Dimension | Status |
|-----------|--------|
| **Document Goal** | CLI, API, future Web/TUI/Telegram/Feishu/WeChat entry points |
| **Current Implementation** | CLI (`cogito` commands) and FastAPI (`cogito-demo`) complete. Single-user, single-key auth. |
| **Completeness** | 80% for CLI, 70% for API |
| **Gaps** | No Web UI/TUI, no Telegram/Feishu/WeChat channels |
| **Next Steps** | Deprioritized per MVP scope |

## 2. Gateway Layer

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Multi-channel gateway with routing, rate limiting, auth, request lifecycle |
| **Current Implementation** | CORS middleware, AuthMiddleware (Bearer token), RateLimitMiddleware, RequestIDMiddleware. Unified error schema. |
| **Completeness** | 65% |
| **Gaps** | No multi-channel routing, no webhook gateway, no background channel. Rate limiting is per-IP only (no per-key/user). |
| **Next Steps** | Add webhook/generic inbound gateway when multi-channel support is needed. |

## 3. Agent Runtime Kernel

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Turn lifecycle, state machine, budget, interrupt/resume, streaming |
| **Current Implementation** | Full turn lifecycle (`RuntimeKernel.process()` + `process_stream()`), state machine (`TurnStateMachine`), budget (`TurnBudget`), interrupt/resume (`interrupt()`/`resume()`), true per-token streaming (`process_stream()`). |
| **Completeness** | 90% |
| **Gaps** | No async runtime support. `StreamGenerator` does not yield tool intents during streaming (tool dispatch happens post-stream). |
| **Next Steps** | Async support for long-running turns. Tool-interrupt during streaming. |

## 4. Context & Reasoning Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Context engine, memory retrieval, budget shares, lineage tracking |
| **Current Implementation** | `ContextEngine.build()`, `MemoryRetriever.search()`, `TurnBudget`, `SourceLineage`. Recent messages + memory retrieval. |
| **Completeness** | 75% |
| **Gaps** | No semantic/vector memory search (FTS5 only). Context window management is basic (last 6 messages). No budget shares per resource (global counters only). |
| **Next Steps** | Add vector embedding search. Implement per-resource budget tracking. |

## 5. Capability Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Tool/function registry, JSON Schema validation, path sandboxing, safe invocation |
| **Current Implementation** | `CapabilityRegistry` with manifest + invoke, JSON Schema validation, path sandboxing (`_resolve_safe_path`), `ToolResult` with status/error/redactions. |
| **Completeness** | 85% |
| **Gaps** | `ToolResult.redactions` field declared but only wired into tracer (not yet in all call sites). No capability hot-reload. |
| **Next Steps** | Ensure `ToolResult.redactions` is used in all tool call paths. Add capability discovery endpoint. |

## 6. Skill Runtime

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Skill execution with steps, preflight, semver, rollback, output normalization |
| **Current Implementation** | `SkillRunner.run()` with capability/transform/LLM steps, preflight policy checks, semver enforcement, rollback compensation, output normalization, step chaining (v0.3). |
| **Completeness** | 80% |
| **Gaps** | LLM step only works if model adapter injected. No step-level timeout. Output normalization truncates at 500 chars. |
| **Next Steps** | Add step timeout. Improve output structure. Add skill scheduling integration. |

## 7. Memory Layer

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Long-term memory with retrieval, candidates, ranking, versioning, pin/archive |
| **Current Implementation** | `MemoryRepository` (CRUD + FTS indexing), `MemoryRetriever` (FTS5 + LIKE + hybrid fallback), `CandidateExtractor`, `MemoryCandidateRepository` (accept/reject), `MemoryEditRepository` (versioning via stale rows), pin/archive (v0.3). |
| **Completeness** | 80% |
| **Gaps** | FTS5 only — no vector/semantic search. No memory ranking/reranking. No background consolidation daemon. |
| **Next Steps** | Add vector embedding for semantic search. Add reranking. Wire maintenance into scheduler. |

## 8. Autonomy Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Scheduled jobs, proactive notifications, daemon loop, quiet hours, retry |
| **Current Implementation** | `SchedulerEngine` (schedule/cancel/tick), `NotificationGate` (quiet hours/duplicate/quota/policy), `ProactiveEngine` (daemon loop), capability invocation in jobs (v0.3), retry with exponential backoff. |
| **Completeness** | 75% |
| **Gaps** | Daemon is sync blocking, no health checks, no async. No cron expression support. No notification delivery channel (gate records only). |
| **Next Steps** | Async daemon loop. Cron parser. Wire notification gate to CLI/API display. |

## 9. Governance Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Policy engine, approval flow, audit logging, deny/allow/escalate decisions |
| **Current Implementation** | `PolicyEngine` with matrix of rules, `ApprovalRepository` (create/resolve), `AuditLogger` (write to audit_logs table), per-context policies (interactive/background), secret deny rules. Approval inline via CLI + API. |
| **Completeness** | 85% |
| **Gaps** | No policy hot-reload. No RBAC. Audit details are JSON strings (no structured query). No per-workspace policy override. |
| **Next Steps** | Add policy reload endpoint. Structured audit query. Workspace-level policy overrides. |

## 10. Trace & Observability Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Distributed tracing, spans, model/tool call logs, redaction, replay |
| **Current Implementation** | `Tracer` (traces/spans), `RedactionHelper` (API key/Bearer/URL/header patterns), `TraceInspector`/replay in CLI, model/tool call logging with latency, export with redaction. Delta-level redaction in API (v0.5). |
| **Completeness** | 80% |
| **Gaps** | No span-level error attribution in all paths. Trace query limited to ID lookup. No metrics/aggregation. |
| **Next Steps** | Add trace query by workspace/time range. Add span attribution for error events. |

## 11. Storage Plane

| Dimension | Status |
|-----------|--------|
| **Document Goal** | SQLite repositories, migrations, export/import, workspace isolation |
| **Current Implementation** | SQLite with 15+ tables, migration system (v2), full export/import, workspace-scoped queries, hard/soft delete, FTS5 indexing. |
| **Completeness** | 85% |
| **Gaps** | No backup/restore CLI. No DB connection pooling. Migration system uses global dict (not thread-safe). |
| **Next Steps** | Add `cogito db backup/restore`. Thread-safe migration registry. |

## 12. Multi-Agent Workspace

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Multiple workspaces, subagent orchestration, cross-workspace memory |
| **Current Implementation** | Workspace isolation (CRUD + per-workspace queries). Subagent support: `RuntimeKernel` can be nested but no orchestration layer. |
| **Completeness** | 20% |
| **Gaps** | No subagent orchestration, no cross-workspace memory sharing, no agent-to-agent communication |
| **Next Steps** | Deprioritized per MVP scope. |

## 13. Data Governance

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Redaction, audit, export, retention policies, PII compliance |
| **Current Implementation** | Redaction in trace/replay/export/API streaming. Audit logging on all mutations. Export with redact flag. Workspace-scoped cleanup. |
| **Completeness** | 70% |
| **Gaps** | No configurable retention policies. No PII detection beyond pattern matching. No user-facing data deletion workflow. |
| **Next Steps** | Add retention policy config. Add PII classification. |

## 14. Production-Grade Deployment & Operations

| Dimension | Status |
|-----------|--------|
| **Document Goal** | Daemon process, health checks, metrics, backup, migration, TLS |
| **Current Implementation** | CLI daemon loop, DB migration system, export/import. No health checks, no metrics, no TLS config. |
| **Completeness** | 30% |
| **Gaps** | No deployment scripts. No Dockerfile. No health endpoint. No metrics (prometheus/openmetrics). No structured logging. No TLS. No secrets management (env vars only). |
| **Next Steps** | Deprioritized per MVP scope. |

---

## Overall Completion Assessment

| Area | Percentage | Notes |
|------|------------|-------|
| **Architecture requirements (full spec)** | 65% | Core Runtime / Governance / Trace / Storage nearly complete. Multi-agent / production ops / channels not started. |
| **Local personal Agent Runtime** | 88% | Single-user, single-workspace runtime is feature-complete for MVP. |
| **Production-grade** | 30% | Missing deployment, TLS, metrics, backup, high availability, secrets management. |

## Summary of Major Gaps (Next Priorities)

1. **Vector/semantic memory search** — Replace FTS5-only retrieval with hybrid embedding search.
2. **Streaming tool-interrupt** — Allow tool calls during streaming (not just post-stream).
3. **Encrypted secret store** — Replace env-var-based secrets with OS keychain or encrypted config.
4. **Production daemon** — Async loop, health checks, metrics, structured logging.
5. **Backup/restore** — CLI commands for DB snapshot and restore.

These gaps are **not implemented** and should not be claimed as complete.

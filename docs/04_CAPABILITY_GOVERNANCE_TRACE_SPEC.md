# 04 Capability, Governance, and Trace Spec

## Capability Types

| Type | Meaning | MVP |
|---|---|---|
| Tool | Single callable function such as file read or search. | Yes, local safe tools only. |
| MCP Server | External MCP tool collection. | No. |
| Plugin | Installable extension bundle. | No. |
| Skill | Reusable multi-step workflow. | Manifest only; runtime in V1. |
| Subagent | Child agent for delegated work. | No. |

## Capability Manifest

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Stable identifier, e.g. `local.file_read`. |
| `version` | yes | Semver. |
| `type` | yes | `tool`, `mcp_server`, `plugin`, `skill`, `subagent`. |
| `description` | yes | Operational description. |
| `input_schema` | yes | JSON Schema or Pydantic-generated schema. |
| `output_schema` | yes | Normalized result schema. |
| `permissions` | yes | Resources and operations requested. |
| `risk_level` | yes | `low`, `medium`, `high`, `critical`. |
| `allowed_contexts` | yes | `interactive`, `approved_background`, `system_maintenance`. |
| `approval_required` | yes | Boolean or rule reference. |
| `audit_required` | yes | Boolean. |
| `idempotent` | yes | Required for retry decisions. |

Example:

```yaml
name: local.file_read
type: tool
risk_level: medium
permissions:
  - resource: workspace_file
    operations: [read]
allowed_contexts: [interactive]
approval_required: false
audit_required: true
idempotent: true
```

## Schema and Result Rules

Inputs must be validated before policy evaluation. Outputs must normalize to:

| Field | Meaning |
|---|---|
| `status` | `ok`, `denied`, `error`, `partial` |
| `summary` | Short model-safe summary. |
| `data` | Structured result, size-limited. |
| `artifacts` | File or object references. |
| `redactions` | Redacted field names/reasons. |
| `lineage` | Source references. |

## Permission and Risk Rules

| Risk | Examples | Default decision |
|---|---|---|
| `low` | Pure calculation, format conversion | `allow` |
| `medium` | Workspace file read, local search | `allow_with_audit` |
| `high` | File write, network request, memory mutation | `require_approval` |
| `critical` | Delete, shell execution, external send, secret access | `deny` in MVP |

## Policy Model

```text
Actor + Capability + Resource + Operation + Context -> Decision
```

Decision types: `allow`, `allow_with_audit`, `require_approval`, `deny`, `escalate`.

Policy matrix:

| Actor | Operation | Context | MVP decision |
|---|---|---|---|
| user | read workspace file | interactive | `allow_with_audit` |
| assistant | write workspace file | interactive | `require_approval` |
| assistant | delete file | interactive | `deny` |
| skill | call network | background | `deny` |
| scheduler | send notification | quiet hours | `deny` |
| system | write trace log | any | `allow_with_audit` |

`escalate` means the local policy cannot decide and requires explicit user/admin configuration. MVP may treat `escalate` as `deny`.

## Approval Rules

Approval requests must show actor, capability, operation, resource, risk, reason, and expected side effect. Approvals are scoped to one call unless a future grant system explicitly widens scope.

## Audit Rules

Audit all writes, sends, deletes, approvals, denials, memory mutations, file reads, and policy escalations. Redact secrets and large payloads. Store enough metadata to explain who did what, when, and why.

## Trace Model

Trace is execution observability. Audit is compliance history. They share identifiers but serve different readers.

| Trace field | Notes |
|---|---|
| `id` | UUID. |
| `workspace_id` | Required. |
| `session_id` | Optional for background work. |
| `root_event_id` | RuntimeEvent ID. |
| `status` | `running`, `completed`, `failed`, `cancelled`. |
| `started_at`, `ended_at` | UTC. |

## Span Model

Span fields: `id`, `trace_id`, `parent_span_id`, `name`, `kind`, `status`, `started_at`, `ended_at`, `input_summary`, `output_summary`, `error`, `metadata_json`.

Span kinds: `runtime`, `context`, `model`, `tool`, `policy`, `approval`, `memory`, `storage`, `result`.

## ToolCall and ModelCall Logs

ToolCall fields: `id`, `trace_id`, `span_id`, `capability_name`, `input_summary`, `decision`, `approval_id`, `status`, `output_summary`, `latency_ms`, `error`.

ModelCall fields: `id`, `trace_id`, `span_id`, `provider`, `model`, `input_token_count`, `output_token_count`, `prompt_summary`, `response_summary`, `latency_ms`, `stop_reason`, `error`.

## Replay and Redaction

Replay must reconstruct state transitions, policy decisions, model/tool summaries, and lineage. MVP replay is read-only trace inspection, not deterministic re-execution. Sensitive data redaction applies to secrets, tokens, credentials, personal identifiers where marked sensitive, and large raw prompts.

## MVP Behavior

Manifest registry, static policy matrix, inline approval, trace/span logs, tool/model call logs, audit rows, response-level lineage, and redaction helpers.

## Future Extensions

Dynamic grants, MCP/plugin manifests, policy DSL, audit export, deterministic replay, subagent trace trees, signed logs, and eval integration.

# 02 Runtime Spec

## Responsibility

The Runtime Kernel advances one turn from input event to final result. It coordinates context building, model calls, capability calls, policy checks, trace/audit logging, memory candidate extraction, retries, interrupts, and result composition.

It must not directly depend on UI channels, provider SDKs, concrete tool implementations, database drivers, or skill internals. It uses interfaces.

## RuntimeEvent Schema

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | UUID. |
| `workspace_id` | string | yes | Isolation boundary. |
| `session_id` | string | yes | Conversation scope. |
| `actor_id` | string | yes | User, system, scheduler, or skill. |
| `source` | enum | yes | `cli`, `api`, `scheduler`, `skill`, `webhook`. |
| `type` | enum | yes | `user_message`, `tool_result`, `approval_result`, `resume`, `interrupt`. |
| `payload` | object | yes | Validated per type. |
| `created_at` | datetime | yes | UTC. |
| `parent_trace_id` | string? | no | For resumed/background work. |

## Turn Lifecycle

```text
receive_event -> create_trace -> load_session -> build_context
-> plan_or_model_call -> maybe_call_capability -> compose_result
-> extract_memory_candidates -> persist -> deliver_result
```

## Turn State Machine

| State | Allowed transitions |
|---|---|
| `received` | `loading_session`, `failed` |
| `loading_session` | `building_context`, `failed` |
| `building_context` | `awaiting_model`, `failed` |
| `awaiting_model` | `evaluating_result`, `calling_tool`, `failed` |
| `calling_tool` | `awaiting_approval`, `evaluating_result`, `retrying`, `failed` |
| `awaiting_approval` | `calling_tool`, `denied`, `interrupted` |
| `evaluating_result` | `composing_result`, `awaiting_model`, `calling_tool`, `failed` |
| `composing_result` | `persisting`, `failed` |
| `persisting` | `completed`, `failed` |
| `retrying` | previous executable state, `failed` |
| `interrupted` | `resuming`, `cancelled` |
| `resuming` | `building_context`, `calling_tool`, `awaiting_model` |
| `completed` | terminal |
| `failed` | terminal |
| `denied` | terminal |
| `cancelled` | terminal |

Invalid transitions must be rejected and logged as trace errors.

## User Request Flow

1. Channel adapter creates a `RuntimeEvent`.
2. Kernel creates trace and root span.
3. Session and workspace are loaded.
4. Context Engine returns ranked context with lineage.
5. Policy checks whether model call is allowed.
6. Model adapter returns assistant message or tool intent.
7. Tool intent goes through capability registry and governance.
8. Result Composer returns final output.
9. Memory candidates, trace, audit, and session messages persist.

## Tool Call Flow

Tool calls are never executed directly from model output. The runtime validates tool intent, resolves a capability manifest, builds a policy request, handles approval if required, executes through the capability interface, normalizes the result, and logs `ToolCall`.

Acceptance criteria: denied tool calls produce a user-visible explanation; approved calls include trace span, audit row, inputs redacted as needed, output summary, and source lineage.

## Model Call Flow

Model calls receive provider-neutral messages, tools allowed for the current context, token budget, and trace metadata. The adapter returns normalized content, tool intents, usage, latency, and provider identifiers.

Acceptance criteria: every call records model name, provider, prompt hash or redacted prompt summary, token usage, latency, stop reason, and error if any.

## Approval Wait Flow

When policy returns `require_approval`, the runtime persists turn state as `awaiting_approval` with approval request data. CLI MVP may ask inline. API later returns an approval token and resumes on `approval_result`.

## Failure and Retry

Retry only transient model/provider/tool failures. Default maximum is 2 retries with exponential backoff. Never retry non-idempotent write/send/delete operations unless the capability declares idempotency.

## Interrupt and Resume

An interrupt persists state, trace, pending capability call, and context lineage. Resume must revalidate policy and budget before continuing.

## Budget Control

Each turn has budgets for wall time, model tokens, model calls, tool calls, and cost estimate. MVP defaults: 1 model call, 2 tool calls, 60 seconds wall time, configurable token limit.

## Result Composition

Final output includes assistant text, tool summaries when relevant, source references, pending approval status, and error summaries. Do not expose secrets or raw internal traces to the user.

## MVP Behavior

MVP supports `cli` user messages, one session, one workspace, one model adapter, simple context retrieval, synchronous tool calls, inline approval, trace/audit persistence, and terminal states.

## Future Extensions

API resume tokens, streaming, background turns, subagent child traces, multi-step plans, durable queues, partial results, and cross-device session sync.

# 05 Autonomy and Skill Spec

## Skill Manifest

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Stable identifier. |
| `version` | yes | Semver. |
| `description` | yes | What the skill does. |
| `inputs` | yes | JSON schema. |
| `outputs` | yes | JSON schema. |
| `steps` | yes | Ordered step declarations. |
| `permissions` | yes | Capability permissions requested. |
| `risk_level` | yes | Highest risk across steps. |
| `rollback` | no | Compensation steps for writes. |
| `owner` | no | Built-in, user, imported. |

Step fields: `id`, `name`, `kind`, `uses_capability`, `input_mapping`, `output_mapping`, `on_error`, `trace_required`.

## Skill Pool and Workspace Skill Copy

Skill Pool stores shared built-in or imported skill definitions. Workspace Skill Copy is the executable copy bound to one workspace, with local configuration, permissions, version pin, and user edits.

Rules:

- Never execute directly from Skill Pool.
- Copy into workspace before execution.
- Changes to pool versions do not mutate existing workspace copies.
- A workspace copy may be disabled without deleting its history.

## Versioning

Use semver. Patch changes do not alter permissions. Minor changes may add optional steps. Major changes may change inputs, outputs, permissions, or behavior and require re-approval.

## Skill Execution

Runtime flow:

```text
resolve workspace skill -> validate input -> policy preflight
-> create trace -> execute steps -> normalize output
-> rollback if needed -> persist run log
```

Each step creates a child span. Capability-using steps must pass through governance. Skill output must include summary, structured result, artifacts, and lineage.

## Permissions and Safety

Skill permissions are the union of step permissions. Background skill execution is more restrictive than interactive execution. Skills cannot request critical operations in MVP. V1 write operations require explicit approval per run or a stored grant.

## Rollback

Rollback is best-effort compensation, not guaranteed transactionality. Any step that writes files, mutates memory, or sends external data must declare whether rollback is possible. MVP records rollback metadata but does not run complex rollback.

## Autonomy Components

| Component | Responsibility | MVP |
|---|---|---|
| Scheduler | Runs one-time or recurring jobs. | No. |
| Proactive Loop | Decides whether to notify user based on context. | No. |
| Drift Runtime | Idle maintenance, summarization, cleanup, research. | No. |
| Notification Gate | Applies quiet hours, deduplication, quota, and safety. | No. |

## Scheduler

Future scheduler jobs include `run_at`, `interval`, `workspace_id`, `actor`, `payload`, `max_retries`, `quiet_hours_policy`, and `enabled`. Jobs must create traces and audit decisions.

## Proactive Loop

The loop evaluates external events and memory/context signals. It may propose notifications, not directly send them. It must score relevance, urgency, confidence, disturbance cost, and deduplication match.

## Drift Runtime

Drift runs background maintenance such as memory consolidation, stale memory detection, index refresh, trace cleanup, and report preparation. It cannot send external messages or perform high-risk writes without approval.

## Notification Gate

Rules:

- Quiet hours block non-critical notifications.
- Deduplicate by event hash, topic, and recent notification history.
- Default quota: no proactive notifications in MVP; future default max 3/day/workspace.
- User feedback options: useful, not useful, too frequent, wrong context, never show again.

## Safety Restrictions for Background Tasks

Background tasks cannot access secrets, delete data, send external messages, run shell commands, or install plugins. They may read accepted memory and write low-risk maintenance records only when policy allows.

## MVP Behavior

MVP includes skill manifest schema drafts only. No scheduler, proactive loop, Drift runtime, notification sending, or background skill execution. Runtime must leave extension points without implementing autonomous behavior.

## V1 Behavior

Workspace skill copies, interactive skill execution, step traces, permission preflight, approval for write steps, simple rollback records, and skill run history.

## V2 Behavior

Scheduler, proactive loop, Drift runtime, notification gate, quotas, quiet hours, feedback learning, background-safe skill subsets, and richer rollback/compensation.

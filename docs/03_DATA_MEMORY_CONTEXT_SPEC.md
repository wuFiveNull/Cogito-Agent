# 03 Data, Memory, and Context Spec

## Core Domain Entities

| Entity | Purpose |
|---|---|
| Workspace | Isolation boundary for sessions, memory, capabilities, and policies. |
| Session | Conversation container within a workspace. |
| Message | User, assistant, system, or tool message. |
| Memory | Long-term remembered fact or preference. |
| MemoryCandidate | Proposed memory awaiting acceptance, rejection, or correction. |
| ContextItem | Ranked item included or considered for a model call. |
| SourceLineage | Link from output/context to original message, file, memory, tool, or model call. |
| FileArtifact | Local file reference or generated artifact metadata. |

## Database Tables

| Table | Important fields |
|---|---|
| `workspaces` | `id`, `name`, `created_at`, `deleted_at` |
| `sessions` | `id`, `workspace_id`, `title`, `status`, `created_at`, `updated_at`, `deleted_at` |
| `messages` | `id`, `workspace_id`, `session_id`, `role`, `content`, `metadata_json`, `created_at`, `deleted_at` |
| `memories` | `id`, `workspace_id`, `type`, `status`, `text`, `summary`, `confidence`, `sensitivity`, `source_id`, `created_at`, `updated_at`, `deleted_at` |
| `memory_candidates` | `id`, `workspace_id`, `session_id`, `text`, `type`, `reason`, `status`, `source_message_id`, `created_at` |
| `context_items` | `id`, `trace_id`, `workspace_id`, `source_type`, `source_id`, `rank`, `token_estimate`, `included`, `reason` |
| `source_lineage` | `id`, `trace_id`, `output_ref`, `source_type`, `source_id`, `span_id`, `note` |
| `file_artifacts` | `id`, `workspace_id`, `path`, `mime_type`, `sha256`, `created_at`, `deleted_at` |

Relationships: workspace owns all data; session owns messages; memory and candidates reference source messages; context items and lineage reference traces/spans.

## Isolation and Deletion

Every user data table must include `workspace_id`. Queries must filter by workspace. Cross-workspace reads are denied unless an explicit migration/export service is running.

Soft delete uses `deleted_at`. Default queries exclude deleted rows. Hard delete is required for user-requested data erasure and must remove or redact derived indexes and lineage references where possible.

## Memory Types

| Type | Example |
|---|---|
| `profile` | User prefers concise engineering answers. |
| `project` | Cogito-Agent MVP uses local SQLite. |
| `relationship` | Contact or organization facts. |
| `task` | Pending follow-up or commitment. |
| `preference` | Output format or workflow preference. |
| `episodic` | Important past interaction. |
| `skill` | Reusable workflow lesson. |

## Memory Lifecycle

```text
candidate -> pending -> accepted -> consolidated -> indexed
-> stale -> archived/deleted
```

MVP may stop at `candidate`, `pending`, `accepted`, and `deleted`.

## Candidate Extraction

After each completed turn, extract candidates only for durable facts, user preferences, project decisions, tasks, and corrections. Do not store secrets, temporary instructions, raw credentials, or sensitive personal data without explicit acceptance.

Candidate fields: `text`, `type`, `reason`, `confidence`, `sensitivity`, `source_message_id`.

## Acceptance and Correction

Accepted memories become searchable. Rejected candidates remain only as audit/debug data unless hard deletion is requested. Corrections create a new memory version and mark the old one `stale` or `archived`.

## Indexing and Retrieval

MVP retrieval uses SQLite FTS5 or simple keyword search. Rank by workspace match, type priority, recency, confidence, direct keyword match, and source reliability. Future retrieval may add embeddings and hybrid BM25/vector ranking.

## Context Sources

- Current user message.
- Recent session messages.
- Accepted memories.
- Relevant files/artifacts.
- Tool results from current turn.
- Skill instructions when a skill is active.
- System/developer policy text.

## Ranking, Trimming, and Budget

Default token allocation:

| Source | MVP budget share |
|---|---|
| System/runtime instructions | 20% |
| Current request | required |
| Recent messages | 30% |
| Retrieved memory | 20% |
| Tool/file context | 20% |
| Response reserve | 10% |

Trim low-ranked context first. Preserve source lineage for included and excluded high-ranking items. Compress only when source text exceeds the budget and summary lineage can be preserved.

## Source Lineage

Each answer segment that depends on memory, file, tool, or prior message should be traceable to `source_type`, `source_id`, `span_id`, and optional quote/hash. MVP may store lineage at response level rather than sentence level.

## Export and Deletion

Export must include sessions, messages, memories, candidates, artifacts metadata, trace summaries, and audit logs. Delete must support workspace-level and memory-level deletion, including indexes.

## MVP Behavior

Single workspace, SQLite tables, recent-message context, accepted memory search, memory candidates, response-level lineage, soft delete, and manual export via repository/service function.

## Future Extensions

Multiple workspaces, memory review UI/API, vector search, memory consolidation jobs, encrypted stores, backup/restore, selective sync, and fine-grained lineage.

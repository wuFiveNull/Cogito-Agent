# v0.10: Core Runtime Hardening

## Goal

Harden the local single-user Agent Runtime by filling three P0/P1 gaps:
- Hybrid Memory Search (vector + FTS5 + recency + pinned boost)
- Streaming Tool Interrupt (proper SSE events for tool dispatch)
- Multi-round Tool Loop (model → tools → model → tools cycle)

## 1. Hybrid Memory Search

### Current State

- `memory/vector.py`: `EmbeddingService` requires `sentence-transformers` (raises `RuntimeError` if missing). `HybridRetriever` exists but only uses FTS5 + cosine similarity — no recency/confidence/pinned boost scoring.
- `memory/retrieval.py`: `MemoryRetriever.search()` uses FTS5-only (no vector). `search_hybrid()` exists but is not called by default.
- `storage/repositories.py`: `MemoryRepository._try_create_embedding()` calls `EmbeddingService()` directly — also raises if `sentence-transformers` not installed.

### Changes

1. **Add `MockEmbeddingService`** to `memory/vector.py`:
   - Returns deterministic random-like vectors (seeded by text hash), no external dependency
   - `EmbeddingService.__init__` falls back to `MockEmbeddingService` when `sentence-transformers` is not installed
   - `_load_model()` catches `ImportError` and sets self to mock fallback

2. **Update `HybridRetriever.search()`** with full hybrid scoring:
   - Combine BM25 score + cosine similarity + recency score + confidence score + pinned boost
   - Score formula: `final = bm25_weight * norm(bm25) + semantic_weight * norm(semantic) + recency_bonus + confidence * 0.5 + (2.0 if pinned else 0)`
   - Recency bonus: `1.0 / (1 + days_since_update)` capped at `1.0`
   - Safe fallback: if no embeddings exist, use FTS5-only scoring

3. **Update `MemoryRetriever.search()`** to use `HybridRetriever` by default:
   - `search()` internally calls `HybridRetriever.search()` if embeddings exist
   - Falls back to FTS5 + LIKE if no embeddings
   - `search_with_lineage()` adds reason for included/excluded items

4. **Update `ContextEngine.build()`** to preserve source lineage:
   - `ContextItem.reason` set to `"included"` or `"excluded: {reason}"` for each memory
   - Persisted via `_persist()` to `source_lineage` table

5. **Migration**: `memory_embeddings` table already exists in `0001_initial.sql`. No new migration needed.

## 2. Streaming Tool Interrupt

### Current State

- `StreamEventType` already has `metadata`, `delta`, `tool_call_started`, `tool_call_completed`, `approval_required`, `final`, `error`
- `process_stream()` already yields these events during streaming
- The flow is: metadata → deltas → tool_call_started → tool_call_completed → final

### Changes

1. **Ensure tool dispatch in streaming goes through full pipeline**:
   - `CapabilityRegistry.invoke()` for capability lookup + JSON Schema validation
   - `PolicyEngine.evaluate()` for policy check
   - `ApprovalRepository` for approval flow
   - `AuditLogger` for audit logging
   - `Tracer.log_tool_call()` for trace logging
   - `RedactionHelper` for redaction

2. **Already verified**: `_dispatch_tools()` (used by both `process()` and `process_stream()`) already covers all the above. No functional changes needed — just tests.

## 3. Multi-round Tool Loop

### Current State

- `_dispatch_tools()` at line 853-867 does a single follow-up model call after tool results
- No loop — max one round of tool results → model

### Changes

1. **Add `max_tool_rounds` config**:
   - `RuntimeKernel.__init__()` parameter: `max_tool_rounds: int = 3`
   - Default value: 3

2. **Convert `_dispatch_tools()` into a loop**:
   - After each round of tool dispatch, check if model response contains new tool intents
   - If yes and rounds < max_tool_rounds, dispatch again
   - Each round: model budget check, tool budget check, trace/audit
   - At max_tool_rounds: return final summary with error message if tool intents remain

3. **Update both `process()` and `process_stream()`** to use the new loop

## Files to Modify

| File | Changes |
|------|---------|
| `memory/vector.py` | MockEmbeddingService, EmbeddingService fallback |
| `memory/retrieval.py` | Hybrid search scoring, default search uses hybrid |
| `runtime/kernel.py` | max_tool_rounds, multi-round loop |
| `runtime/budget.py` | (optional) max_tool_rounds field |
| `docs/19_V0_10_CORE_RUNTIME_HARDENING_PLAN.md` | This file |

## Files to Add

| File | Content |
|------|---------|
| `tests/test_v0_10_hybrid_memory.py` | Hybrid search tests |
| `tests/test_v0_10_streaming_tools.py` | Streaming tool tests |
| `tests/test_v0_10_tool_loop.py` | Multi-round tool loop tests |

## Verification

- `pytest` all pass (target: 1043+)
- `ruff check src/` clean
- `mypy src/` clean

## Not in Scope

- No new Console UI changes
- No multi-user/OAuth/RBAC
- No Telegram/Feishu real integration
- No cloud sync or plugin marketplace
- No async runtime

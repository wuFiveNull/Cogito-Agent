# V0.13: Workspace Files + Artifact System Plan

## Goal

Give the agent the ability to read, index, search, and reference workspace files; give skills the ability to produce persistent, traceable, and downloadable artifacts (reports, summaries, generated code, etc.).

## Design Decisions

- **Path Safety**: `WorkspaceFileRegistry` sandboxes all file operations to registered root directories. Path traversal (`../`) and symlink escapes are explicitly denied. SHA256 hashing on ingestion for integrity tracking.
- **Chunk + FTS5**: Files are split into fixed-size overlapping chunks (512 chars, 64 overlap) and indexed in SQLite FTS5 for full-text search. No external search index needed.
- **Embedding Fallback**: When `sentence-transformers` is not installed, `FileRetriever` falls back to hash-based `MockEmbeddingService` for semantic search (same approach as `HybridRetriever`).
- **Artifact Types**: Markdown (rendered HTML), JSON (pretty-printed), text (plain `<pre>`). New types can be added via switch in `ArtifactService.render_artifact_html()`.
- **Skill Artifacts**: Builtin skills (e.g., `project_status`) can create artifacts via `ArtifactService.create()` and link them to inbox notifications. All artifact mutations are audit-logged.
- **Console Pages**: Workspace Files page at `/console/workspace/files`; Artifacts page at `/console/artifacts`. Both follow existing console patterns (menu, auth, redaction, templates).

## What Not to Build (v0.13)

- No binary file parsing (Office docs, PDFs) — only UTF-8 text files.
- No live file watching (inotify) — manual scan only.
- No vector database — uses SQLite FTS5 + mock embeddings.
- No artifact versioning — single version per artifact.
- No artifact sharing/export beyond download.
- No artifact search — artifact list is paginated via SQL.
- No file diffing or merge — single-file index only.

## Implementation Order

1. Migration v9 (tables: workspace_roots, workspace_files, file_chunks, file_chunk_embeddings, file_chunks_fts, artifacts)
2. WorkspaceFileRegistry (root registration, file CRUD, path safety, ignore patterns)
3. FileIngestionService (scan, text extraction, chunking)
4. FileRetriever (FTS5 search + embedding fallback)
5. ArtifactService (CRUD + render + audit)
6. File capabilities (5 new manifests)
7. Console views + templates (workspace files, artifacts)
8. Upgrade project_status skill (real implementation)
9. Tests (44 new)

from __future__ import annotations

from cogito_agent.storage import Database


class FileRetriever:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        use_embedding: bool = True,
    ) -> list[dict[str, object]]:
        if use_embedding:
            results = self._search_embedding(workspace_id, query, limit)
            if results:
                return results
        return self._search_fts(workspace_id, query, limit)

    def _search_fts(
        self, workspace_id: str, query: str, limit: int = 10
    ) -> list[dict[str, object]]:
        sanitized = " ".join(
            word for word in query.split() if word not in ("AND", "OR", "NOT", "NEAR")
        )
        if not sanitized:
            return []
        fts_query = " OR ".join(
            f'"{word}"' if " " not in word else word for word in sanitized.split()
        )
        try:
            cur = self._db.connection.execute(
                "SELECT fc.id, fc.workspace_file_id, fc.workspace_id,"
                " fc.chunk_index, fc.text, fc.token_count,"
                " fc.start_line, fc.end_line, fc.sha256,"
                " wf.file_name, wf.relative_path,"
                " rank"
                " FROM file_chunks_fts"
                " JOIN file_chunks fc ON file_chunks_fts.rowid = fc.rowid"
                " JOIN workspace_files wf ON wf.id = fc.workspace_file_id"
                " WHERE file_chunks_fts MATCH ?"
                " AND fc.workspace_id = ? AND wf.status = 'active'"
                " ORDER BY rank"
                " LIMIT ?",
                (fts_query, workspace_id, limit),
            )
            rows = cur.fetchall()
            results: list[dict[str, object]] = []
            for row in rows:
                r = dict(row)
                r["score"] = float(row["rank"]) if row["rank"] is not None else 0.0
                r["source_lineage"] = {
                    "type": "file_chunk",
                    "file_id": row["workspace_file_id"],
                    "file_name": row["file_name"],
                    "path": row["relative_path"],
                    "lines": f"{row['start_line']}-{row['end_line']}",
                    "chunk_id": row["id"],
                }
                results.append(r)
            return results
        except Exception:
            return []

    def _search_embedding(
        self, workspace_id: str, query: str, limit: int = 10
    ) -> list[dict[str, object]]:
        try:
            from cogito_agent.embedding.service import (
                _unpack_embedding,
                create_embedding_provider_from_config,
            )
            from cogito_agent.config import Settings

            provider = create_embedding_provider_from_config(Settings.get().memory.embedding)
            if provider is None:
                return []
            query_vec = provider.embed_text(query)
            all_chunks = self._db.connection.execute(
                "SELECT fc.id, fc.workspace_file_id, fc.chunk_index, fc.text,"
                " fc.start_line, fc.end_line, fc.token_count,"
                " wf.file_name, wf.relative_path,"
                " fce.embedding"
                " FROM file_chunks fc"
                " JOIN workspace_files wf ON wf.id = fc.workspace_file_id"
                " JOIN file_chunk_embeddings fce ON fce.chunk_id = fc.id"
                " WHERE fc.workspace_id = ? AND wf.status = 'active'"
                " AND fce.embedding IS NOT NULL",
                (workspace_id,),
            ).fetchall()
            if not all_chunks:
                return []
            import numpy as np

            scored: list[tuple[float, dict[str, object]]] = []
            for row in all_chunks:
                row_dict = dict(row)
                stored_vec = _unpack_embedding(row["embedding"])
                score = float(np.dot(query_vec, stored_vec))
                row_dict["score"] = min(1.0, max(0.0, score))
                row_dict["source_lineage"] = {
                    "type": "file_chunk",
                    "file_id": row["workspace_file_id"],
                    "file_name": row["file_name"],
                    "path": row["relative_path"],
                    "lines": f"{row['start_line']}-{row['end_line']}",
                    "chunk_id": row["id"],
                }
                if score > 0.3:
                    scored.append((score, row_dict))
            scored.sort(key=lambda x: -x[0])
            return [item for _, item in scored[:limit]]
        except Exception:
            return []

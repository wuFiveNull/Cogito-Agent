from __future__ import annotations

import json
import uuid

from cogito_agent.shared.skill import SkillManifest
from cogito_agent.storage import Database


class SkillPool:
    def __init__(self, db: Database) -> None:
        self._db = db

    def install(self, manifest: SkillManifest) -> dict[str, object]:
        sid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO skill_pool (id, name, version, description, manifest_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                sid,
                manifest.name,
                manifest.version,
                manifest.description,
                manifest.model_dump_json(),
            ),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT * FROM skill_pool WHERE id = ?", (sid,))
        return dict(cur.fetchone())

    def get(self, name: str, version: str = "") -> dict[str, object] | None:
        if version:
            cur = self._db.connection.execute(
                "SELECT * FROM skill_pool WHERE name = ? AND version = ?",
                (name, version),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM skill_pool WHERE name = ? ORDER BY rowid DESC LIMIT 1",
                (name,),
            )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict[str, object]]:
        cur = self._db.connection.execute("SELECT * FROM skill_pool ORDER BY name, version")
        return [dict(r) for r in cur.fetchall()]


class WorkspaceSkill:
    def __init__(self, db: Database) -> None:
        self._db = db

    def copy_from_pool(self, workspace_id: str, pool_skill_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute("SELECT * FROM skill_pool WHERE id = ?", (pool_skill_id,))
        pool = cur.fetchone()
        if pool is None:
            return None

        wsid = str(uuid.uuid4())
        manifest = json.loads(pool["manifest_json"])
        self._db.connection.execute(
            "INSERT INTO workspace_skills"
            " (id, workspace_id, pool_skill_id, name, version, description, manifest_json, enabled)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (
                wsid,
                workspace_id,
                pool_skill_id,
                manifest["name"],
                manifest["version"],
                manifest.get("description", ""),
                json.dumps(manifest),
            ),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT * FROM workspace_skills WHERE id = ?", (wsid,))
        return dict(cur.fetchone())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM workspace_skills WHERE workspace_id = ? ORDER BY name",
            (workspace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get(self, wsid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute("SELECT * FROM workspace_skills WHERE id = ?", (wsid,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_name(self, name: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM workspace_skills WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def set_enabled(self, wsid: str, enabled: bool) -> None:
        self._db.connection.execute(
            "UPDATE workspace_skills SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, wsid),
        )
        self._db.connection.commit()

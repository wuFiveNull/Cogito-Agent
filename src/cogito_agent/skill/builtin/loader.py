from __future__ import annotations

from cogito_agent.shared.skill import SkillManifest
from cogito_agent.skill.storage import SkillPool
from cogito_agent.storage import Database

from .daily_brief import DAILY_BRIEF_MANIFEST
from .inbox_digest import INBOX_DIGEST_MANIFEST
from .memory_consolidation import MEMORY_CONSOLIDATION_MANIFEST
from .memory_optimizer import MEMORY_OPTIMIZER_MANIFEST
from .project_status import PROJECT_STATUS_MANIFEST
from .task_extraction import TASK_EXTRACTION_MANIFEST
from .trace_review import TRACE_REVIEW_MANIFEST

BUILTIN_SKILL_MANIFESTS: list[SkillManifest] = [
    PROJECT_STATUS_MANIFEST,
    DAILY_BRIEF_MANIFEST,
    MEMORY_CONSOLIDATION_MANIFEST,
    MEMORY_OPTIMIZER_MANIFEST,
    TASK_EXTRACTION_MANIFEST,
    TRACE_REVIEW_MANIFEST,
    INBOX_DIGEST_MANIFEST,
]


class BuiltinSkillLoader:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._pool = SkillPool(db)

    def load_all(self) -> list[dict[str, object]]:
        loaded: list[dict[str, object]] = []
        for manifest in BUILTIN_SKILL_MANIFESTS:
            result = self._ensure_skill(manifest)
            if result:
                loaded.append(result)
        return loaded

    def load(self, name: str) -> dict[str, object] | None:
        for manifest in BUILTIN_SKILL_MANIFESTS:
            if manifest.name == name:
                return self._ensure_skill(manifest)
        return None

    def _ensure_skill(self, manifest: SkillManifest) -> dict[str, object] | None:
        existing = self._pool.get(manifest.name, manifest.version)
        if existing is not None:
            return existing
        try:
            return self._pool.install(manifest)
        except Exception:
            return None

from __future__ import annotations

import os
from pathlib import Path

from .database import Database, register_migration
from .repositories import (
    ApprovalRepository,
    AttachmentRepository,
    AuditRepository,
    DaemonStateRepository,
    DecisionRepository,
    DriftRunRepository,
    DriftStateRepository,
    FileArtifactRepository,
    MemeAssetRepository,
    MemoryEditRepository,
    MemoryItemRepository,
    MemoryRepository,
    MessageRepository,
    ModelCallRepository,
    OutboxRepository,
    SessionRepository,
    ToolCallRepository,
    TraceRepository,
    VisionObservationRepository,
    WorkspaceRepository,
)

# Re-exported for convenience, but the primary workspace layer
# is accessed via workspace/ subpackage.

__all__ = [
    "ApprovalRepository",
    "AttachmentRepository",
    "AuditRepository",
    "Database",
    "DaemonStateRepository",
    "DecisionRepository",
    "DriftRunRepository",
    "DriftStateRepository",
    "FileArtifactRepository",
    "MemeAssetRepository",
    "MemoryEditRepository",
    "MemoryItemRepository",
    "MemoryRepository",
    "MessageRepository",
    "ModelCallRepository",
    "OutboxRepository",
    "SessionRepository",
    "ToolCallRepository",
    "TraceRepository",
    "VisionObservationRepository",
    "WorkspaceRepository",
    "register_migration",
    "get_db",
    "reset_db",
]

# ── Shared database singleton ─────────────────────────────────────────────

_db: Database | None = None


def get_db() -> Database:
    """Return the global Database singleton, creating & migrating it on first call.

    All consumers (API endpoints, console views, CLI) should obtain their
    ``Database`` instance through this function to share a single connection
    and avoid redundant migration runs.
    """
    global _db
    if _db is None:
        db_path = os.environ.get("COGITO_DB_PATH", ":memory:")
        if db_path != ":memory:":
            db_path = str(Path(db_path).expanduser())
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _db = Database(db_path)
        _db.initialize()
        _db.migrate()
    return _db


def reset_db() -> None:
    """Reset the global DB singleton, closing the current connection if any.

    Used primarily by ``backup_views`` during restore operations.
    """
    global _db
    if _db is not None:
        _db.close()
    _db = None

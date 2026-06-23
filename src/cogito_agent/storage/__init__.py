from __future__ import annotations

import contextvars
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
    "set_request_db",
]

# ── Request-scoped DB (contextvars) ──────────────────────────────────────────
# Allows Console/API apps to inject the per-request DB connection without
# changing any existing ``from cogito_agent.storage import get_db`` calls.

_request_db: contextvars.ContextVar[Database | None] = contextvars.ContextVar(
    "_request_db", default=None
)


def set_request_db(db: Database | None) -> None:
    """Set the request-scoped Database connection.

    Used by middleware in :mod:`cogito_agent.console.app` to inject the
    correct DB connection for each request.  When set, ``get_db()``
    returns this connection instead of the global singleton.
    """
    _request_db.set(db)


# ── Shared database singleton ─────────────────────────────────────────────

_db: Database | None = None


def get_db() -> Database:
    """Return a ``Database`` connection.

    Resolution order:

    1. Request-scoped connection (set via :func:`set_request_db`)
    2. Global singleton (created on first call)
    """
    ctx_db = _request_db.get()
    if ctx_db is not None:
        return ctx_db
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

from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

_BUILT_STATIC_HASH: str | None = None


def _compute_static_hash() -> str:
    hasher = hashlib.sha256()
    css_path = HERE / "static" / "console.css"
    if css_path.is_file():
        hasher.update(css_path.read_bytes())
    js_path = HERE / "static" / "htmx.min.js"
    if js_path.is_file():
        hasher.update(js_path.read_bytes())
    digest = hasher.hexdigest()[:12]
    return digest


def get_static_version() -> str:
    global _BUILT_STATIC_HASH
    if _BUILT_STATIC_HASH is None:
        _BUILT_STATIC_HASH = _compute_static_hash()
    return _BUILT_STATIC_HASH


def static_url(path: str) -> str:
    ver = get_static_version()
    return f"/console/static/{path}?v={ver}"


STATIC_VERSION: str = get_static_version()

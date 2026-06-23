"""Message type registry — decorator-based registration.

Allows message renderers to self-register via ``@register("type")``
without needing to import every renderer in the same place.
"""

from __future__ import annotations

from textual.widgets import Static

_DISPATCH: dict[str, type[Static]] = {}


def register(msg_type: str):
    """Decorator: register a Widget class as the renderer for ``msg_type``.

    Usage::

        @register("user")
        class UserMessage(Static):
            ...
    """
    def decorator(cls: type[Static]) -> type[Static]:
        _DISPATCH[msg_type] = cls
        return cls
    return decorator


def get_handler(msg_type: str) -> type[Static] | None:
    """Return the registered Widget class for ``msg_type``."""
    return _DISPATCH.get(msg_type)


def all_types() -> dict[str, type[Static]]:
    """Return a copy of the full dispatch map."""
    return dict(_DISPATCH)

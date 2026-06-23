"""Semantic color tokens — every component references these, never raw colors.

All values are standard Textual CSS variable names that are available
from any registered Theme.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticColors:
    """Named semantic tokens resolved from the active theme.

    Each value is a standard Textual CSS variable name.
    """

    text_primary: str = "$text"
    text_secondary: str = "$text-disabled"
    text_accent: str = "$accent"
    text_response: str = "$text"
    background_primary: str = "$surface"
    background_message: str = "$boost"
    background_input: str = "$boost"
    status_error: str = "$error"
    status_success: str = "$success"
    status_warning: str = "$warning"
    border_default: str = "$border"

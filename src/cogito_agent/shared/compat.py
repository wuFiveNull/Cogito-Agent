"""Python 3.8 compatibility shims.

The project requires Python 3.12+, but this module provides minimal
backports for running on Python 3.8 during development/testing.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):

    from enum import Enum

    class StrEnum(str, Enum):
        pass

    from datetime import timezone

    UTC = timezone.utc
else:
    from datetime import UTC  # noqa: F401
    from enum import StrEnum  # noqa: F401

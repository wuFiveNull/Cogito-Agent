"""Pytest configuration: ensures Python 3.12 features work on 3.8."""
import sys

if sys.version_info < (3, 11):
    import enum

    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum

    import datetime

    datetime.UTC = datetime.timezone.utc

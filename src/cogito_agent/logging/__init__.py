from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from pythonjsonlogger import json as _json_logger

from cogito_agent.config.loader import LoggingSettings


def setup_logging(
    settings: LoggingSettings | None = None,
) -> None:
    if settings is None:
        from cogito_agent.config.loader import CogitoConfig

        cfg = CogitoConfig()
        settings = cfg.logging

    level = getattr(logging, settings.level.upper(), logging.INFO)
    log_format = settings.format

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    if log_format == "json":
        formatter: Any = _json_logger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            timestamp="iso",
        )
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

        log_dir = os.path.expanduser("~/.cogito/logs")
        log_path = os.path.join(log_dir, "cogito.log")
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=settings.max_size,
                backupCount=settings.backup_count,
                encoding="utf-8",
            )
        except OSError as exc:
            # A read-only home directory must not prevent the service from
            # starting. Structured stdout remains available to supervisors.
            root_logger.warning("File logging unavailable: %s", exc)
        else:
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_log_path() -> str:
    return os.path.join(os.path.expanduser("~/.cogito/logs"), "cogito.log")

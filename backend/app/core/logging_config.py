"""Structured JSON logging.

Production deployments should ship logs as JSON to a collector (Loki, ELK,
CloudWatch). In development, set LOG_JSON=false for human-readable output.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

from app.core.config import settings


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.app = settings.APP_NAME
        record.env = settings.APP_ENV
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Wipe existing handlers (pytest etc. may have installed some)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())

    if settings.LOG_JSON:
        fmt = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(app)s %(env)s",
            rename_fields={"levelname": "level", "asctime": "timestamp"},
        )
    else:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root.addHandler(handler)

    # Tame chatty libs. `httpx` logs one INFO line PER REQUEST, and the Yahoo
    # gap-filler feed polls ~30 symbols every 10 s — left at INFO that alone
    # writes ~260k journal lines a day and buries every real message.
    for noisy in ("uvicorn.access", "pymongo", "motor", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_extra(**kwargs: Any) -> dict[str, Any]:
    """Helper for adding structured fields: logger.info("msg", extra=log_extra(user_id=x))."""
    return {"extra_fields": kwargs}

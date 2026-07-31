"""JSON logging with stable forecast context fields."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, pretty: bool = False) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    processors.append(
        structlog.dev.ConsoleRenderer() if pretty else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def logger(**context: Any) -> Any:
    """Return a bound logger; all pipeline logs share these machine fields."""
    return structlog.get_logger().bind(**context)

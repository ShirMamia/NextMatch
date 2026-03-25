"""
Logging setup — call configure_logging() once at application startup.

Uses Python's standard logging with a structured format.
Log level is read from AppConfig (already validated there).
Timestamps are always UTC.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import time


def configure_logging(log_level: str = "INFO") -> None:
    """Configure the root logger for the application.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR.
                   Assumed to be pre-validated by config.py.
                   Raises ValueError if the level is not recognised.
    """
    level = getattr(logging, log_level.upper(), None)
    if level is None:
        raise ValueError(
            f"Unrecognised log level '{log_level}'. "
            "Must be one of: DEBUG, INFO, WARNING, ERROR."
        )

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # re-configure if already initialised (e.g. in tests)
    )

    # Use UTC for all log timestamps.
    logging.Formatter.converter = time.gmtime

    # Suppress verbose third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger by name."""
    return logging.getLogger(name)

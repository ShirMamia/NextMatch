"""
Time utilities — always UTC, always timezone-aware.

All functions require timezone-aware datetimes and normalize to UTC.
Passing a naive datetime raises ValueError immediately.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _require_aware(dt: datetime) -> datetime:
    """Normalize to UTC. Raises ValueError if dt is naive."""
    if dt.tzinfo is None:
        raise ValueError(
            f"Expected a timezone-aware datetime, got naive datetime: {dt!r}. "
            "Use utc_now() or attach tzinfo before passing to time utilities."
        )
    return dt.astimezone(timezone.utc)


def format_date(dt: datetime) -> str:
    """Return a UTC date string (YYYY-MM-DD).

    Raises:
        ValueError: if dt is a naive datetime.
    """
    return _require_aware(dt).strftime("%Y-%m-%d")


def format_datetime(dt: datetime) -> str:
    """Return a UTC datetime string (YYYY-MM-DD HH:MM UTC).

    Raises:
        ValueError: if dt is a naive datetime.
    """
    return _require_aware(dt).strftime("%Y-%m-%d %H:%M UTC")

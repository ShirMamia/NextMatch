"""ID generation utilities."""
from __future__ import annotations

import uuid


def generate_id() -> str:
    """Generate a new random UUID4 string (no hyphens)."""
    return uuid.uuid4().hex

"""
Configuration — loaded once at startup from environment variables.

Usage:
    from app.services.config import get_config
    cfg = get_config()

Design decisions:
  - anthropic_api_key is optional at app startup. The shell and all
    non-LLM features run without it. llm_client.py raises at call time
    if the key is missing.
  - All paths (including env-provided ones) are resolved relative to the
    project root, not the current working directory.
  - log_level uses a Literal field; invalid values raise ValueError
    immediately instead of silently falling back.
  - anthropic_api_key is stored as SecretStr to prevent accidental logging.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

# Resolve project root: this file lives at app/services/config.py
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
_ENV_FILE = _PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=_ENV_FILE, override=False)

_DEFAULT_MODEL = "claude-sonnet-4-6"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


def _resolve_path(env_val: str, default: Path) -> Path:
    """Return env_val resolved relative to project root, or default if empty."""
    if not env_val:
        return default
    p = Path(env_val)
    return (_PROJECT_ROOT / p).resolve() if not p.is_absolute() else p.resolve()


class AppConfig(BaseModel):
    model_config = {"extra": "forbid"}

    # Optional at startup; required only when making LLM calls.
    anthropic_api_key: SecretStr | None = None
    model: str = _DEFAULT_MODEL
    data_dir: Path = Field(default_factory=lambda: _PROJECT_ROOT / "data")
    outputs_dir: Path = Field(default_factory=lambda: _PROJECT_ROOT / "outputs")
    log_level: LogLevel = "INFO"


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and validate application config from environment variables.

    Does not require ANTHROPIC_API_KEY to succeed. The LLM client
    enforces that the key is present when a call is attempted.

    Raises:
        ValueError: if NEXTMATCH_LOG_LEVEL is set to an unrecognised value.
    """
    raw_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    api_key: SecretStr | None = SecretStr(raw_key) if raw_key else None

    model = os.environ.get("NEXTMATCH_MODEL", "").strip() or _DEFAULT_MODEL

    data_dir = _resolve_path(
        os.environ.get("NEXTMATCH_DATA_DIR", "").strip(),
        _PROJECT_ROOT / "data",
    )
    outputs_dir = _resolve_path(
        os.environ.get("NEXTMATCH_OUTPUTS_DIR", "").strip(),
        _PROJECT_ROOT / "outputs",
    )

    raw_log = os.environ.get("NEXTMATCH_LOG_LEVEL", "INFO").strip().upper()
    if raw_log not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid NEXTMATCH_LOG_LEVEL '{raw_log}'. "
            f"Must be one of: {', '.join(sorted(_VALID_LOG_LEVELS))}."
        )
    log_level: LogLevel = raw_log  # type: ignore[assignment]

    config = AppConfig(
        anthropic_api_key=api_key,
        model=model,
        data_dir=data_dir,
        outputs_dir=outputs_dir,
        log_level=log_level,
    )

    # Ensure storage directories exist at startup.
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)

    return config

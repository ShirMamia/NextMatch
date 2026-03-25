"""
File store — JSON-based implementation of the Repository interface.

Each collection is stored as a single JSON file: {data_dir}/{collection}.json
The file contains a flat dict mapping key → record.

Safety properties:
  - Missing collection files are treated as empty (returns {}).
  - Existing but corrupted/unreadable files raise PersistenceError (no data loss).
  - Writes use atomic rename (write temp → replace) to prevent partial writes.
  - json.dump uses no default converter; non-serializable values fail loudly.
  - Collection names are validated to prevent unsafe file paths.

This is the V1 persistence layer. Suitable for single-user, single-process use.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from app.storage.repository import Repository

logger = logging.getLogger(__name__)

# Only alphanumeric, underscores, and hyphens allowed in collection names.
_VALID_COLLECTION = re.compile(r"^[a-zA-Z0-9_-]+$")


class PersistenceError(Exception):
    """Raised when a storage read or write operation fails unrecoverably."""


def _validate_collection(collection: str) -> None:
    if not _VALID_COLLECTION.match(collection):
        raise ValueError(
            f"Invalid collection name '{collection}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )


class FileStore(Repository):
    """Persists collections as JSON files under a configurable directory."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _collection_path(self, collection: str) -> Path:
        _validate_collection(collection)
        return self._data_dir / f"{collection}.json"

    def _load_collection(self, collection: str) -> dict[str, Any]:
        path = self._collection_path(collection)
        if not path.exists():
            return {}
        # File exists: any read or parse failure is a hard error.
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise PersistenceError(
                f"Collection file '{path}' is corrupted (invalid JSON): {exc}"
            ) from exc
        except OSError as exc:
            raise PersistenceError(
                f"Could not read collection file '{path}': {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise PersistenceError(
                f"Collection file '{path}' has unexpected format "
                f"(expected dict, got {type(data).__name__})."
            )
        return data

    def _save_collection(self, collection: str, data: dict[str, Any]) -> None:
        path = self._collection_path(collection)
        # Write to a temp file in the same directory, then atomically replace.
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._data_dir,
                suffix=".tmp",
                delete=False,
            ) as tmp:
                json.dump(data, tmp, indent=2, ensure_ascii=False)
                tmp_path = Path(tmp.name)
        except (OSError, TypeError) as exc:
            raise PersistenceError(
                f"Failed to write collection '{collection}': {exc}"
            ) from exc
        try:
            tmp_path.replace(path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise PersistenceError(
                f"Failed to replace collection file '{path}': {exc}"
            ) from exc

    # --- Repository interface ---

    def save(self, collection: str, key: str, value: dict[str, Any]) -> None:
        data = self._load_collection(collection)
        data[key] = value
        self._save_collection(collection, data)
        logger.debug("Saved key='%s' to collection='%s'", key, collection)

    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        return self._load_collection(collection).get(key)

    def load_all(self, collection: str) -> list[dict[str, Any]]:
        return list(self._load_collection(collection).values())

    def delete(self, collection: str, key: str) -> bool:
        data = self._load_collection(collection)
        if key not in data:
            return False
        del data[key]
        self._save_collection(collection, data)
        logger.debug("Deleted key='%s' from collection='%s'", key, collection)
        return True

    def exists(self, collection: str, key: str) -> bool:
        return key in self._load_collection(collection)

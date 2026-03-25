"""
Repository interface — abstract base for all persistence operations.

FileStore (file_store.py) implements this interface for V1.
SqliteStore (sqlite_store.py) is stubbed for a later phase.

All concrete stores must implement every method defined here.
The interface is intentionally minimal for Slice 1.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Repository(ABC):
    """Abstract persistence interface for NextMatch domain objects.

    Keys are string identifiers (e.g. candidate_id, job_id).
    Values are plain dicts (JSON-serialisable) or Pydantic model dicts.
    Collections are named string namespaces (e.g. "candidates", "jobs").
    """

    @abstractmethod
    def save(self, collection: str, key: str, value: dict[str, Any]) -> None:
        """Persist a single record under the given key in the collection.

        Creates or overwrites the record.
        """

    @abstractmethod
    def load(self, collection: str, key: str) -> dict[str, Any] | None:
        """Load a single record by key from the collection.

        Returns None if the key does not exist.
        """

    @abstractmethod
    def load_all(self, collection: str) -> list[dict[str, Any]]:
        """Load all records in the collection.

        Returns an empty list if the collection does not exist.
        """

    @abstractmethod
    def delete(self, collection: str, key: str) -> bool:
        """Delete a record by key from the collection.

        Returns True if the record existed and was deleted, False otherwise.
        """

    @abstractmethod
    def exists(self, collection: str, key: str) -> bool:
        """Return True if a record with the given key exists in the collection."""

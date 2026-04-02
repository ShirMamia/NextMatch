"""
Tracker service — Slice 8.

Provides ApplicationRecord CRUD through the storage layer.

Public interface:
  TrackerService.save_application(record)
  TrackerService.get_application(application_id) → ApplicationRecord | None
  TrackerService.list_applications()            → list[ApplicationRecord]
  TrackerService.update_status(application_id, new_status) → ApplicationRecord

All persistence goes through the Repository interface; no direct file I/O here.
Status-change logic handles applied_at automatically to keep records consistent
with ApplicationRecord schema constraints.

Dashboard metrics and export are NOT implemented here — that is Slice 9.
"""
from __future__ import annotations

import logging

from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.storage.repository import Repository
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

_COLLECTION = "applications"

# Statuses that require applied_at to be set.
_REQUIRES_APPLIED_AT: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
})

# Statuses that require applied_at to be None.
_NO_APPLIED_AT: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.DISCOVERED,
    ApplicationStatus.SAVED,
    ApplicationStatus.TAILORED,
    ApplicationStatus.APPROVED,
})


class TrackerService:
    """Application record CRUD over the storage layer."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def save_application(self, record: ApplicationRecord) -> ApplicationRecord:
        """Persist an ApplicationRecord, creating or overwriting by application_id.

        Returns the saved record so callers can use the persisted object directly.
        """
        self._repo.save(
            _COLLECTION,
            record.application_id,
            record.model_dump(mode="json"),
        )
        logger.debug(
            "Saved application '%s' (status=%s)",
            record.application_id,
            record.status.value,
        )
        return record

    def get_application(self, application_id: str) -> ApplicationRecord | None:
        """Load a single ApplicationRecord by ID. Returns None if not found."""
        raw = self._repo.load(_COLLECTION, application_id)
        if raw is None:
            return None
        return ApplicationRecord.model_validate(raw)

    def list_applications(self) -> list[ApplicationRecord]:
        """Return all saved ApplicationRecords, sorted newest first."""
        records = [
            ApplicationRecord.model_validate(r)
            for r in self._repo.load_all(_COLLECTION)
        ]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def update_status(
        self,
        application_id: str,
        new_status: ApplicationStatus,
    ) -> ApplicationRecord:
        """
        Update the status of an existing application.

        Automatically sets applied_at when transitioning to a status that
        requires it, and clears it when returning to a pre-application status.
        The updated record is fully revalidated before saving.

        Args:
            application_id: ID of the record to update.
            new_status:     The target ApplicationStatus.

        Returns:
            The updated and revalidated ApplicationRecord.

        Raises:
            ValueError: if no application with the given ID is found.
        """
        record = self.get_application(application_id)
        if record is None:
            raise ValueError(f"No application found with id '{application_id}'")

        now = utc_now()
        merged = record.model_dump(mode="json")
        merged["status"] = new_status.value
        merged["updated_at"] = now.isoformat()

        if new_status in _REQUIRES_APPLIED_AT and record.applied_at is None:
            merged["applied_at"] = now.isoformat()
        elif new_status in _NO_APPLIED_AT:
            merged["applied_at"] = None

        updated = ApplicationRecord.model_validate(merged)
        self.save_application(updated)
        logger.debug(
            "Updated application '%s': %s → %s",
            application_id,
            record.status.value,
            new_status.value,
        )
        return updated

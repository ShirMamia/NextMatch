"""
Application record schema — Slice 1 foundation.

ApplicationRecord is the tracker entry for a candidate-job application.

Status lifecycle:
  DISCOVERED → SAVED → TAILORED → APPROVED → APPLIED → INTERVIEWING → OFFERED
                                                      ↘ REJECTED / WITHDRAWN

Consistency rules enforced by this schema:
  1. applied_at must be None for all pre-application statuses
     (DISCOVERED, SAVED, TAILORED, APPROVED).
  2. applied_at must be set for APPLIED and all later statuses.
  3. resume_id must be set for APPROVED and all later statuses.

Status transition validation is owned by reporting/tracker.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"
    SAVED = "saved"
    TAILORED = "tailored"
    APPROVED = "approved"    # resume approved by candidate; ready to apply
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFERED = "offered"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# applied_at must be None for these statuses.
_NO_APPLIED_AT_STATUSES: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.DISCOVERED,
    ApplicationStatus.SAVED,
    ApplicationStatus.TAILORED,
    ApplicationStatus.APPROVED,
})

# applied_at must be set for these statuses.
_REQUIRES_APPLIED_AT_STATUSES: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
})

# resume_id must be set for APPROVED and all later statuses.
_REQUIRES_RESUME_ID_STATUSES: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.APPROVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
})


class ApplicationRecord(BaseModel):
    model_config = {"extra": "forbid"}

    application_id: str
    job_id: str
    candidate_id: str
    resume_id: str | None = None    # required once status reaches APPROVED
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    applied_at: datetime | None = None
    notes: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def check_field_consistency(self) -> ApplicationRecord:
        if self.status in _NO_APPLIED_AT_STATUSES and self.applied_at is not None:
            raise ValueError(
                f"applied_at must be None when status is '{self.status.value}'"
            )
        if self.status in _REQUIRES_APPLIED_AT_STATUSES and self.applied_at is None:
            raise ValueError(
                f"applied_at must be set when status is '{self.status.value}'"
            )
        if self.status in _REQUIRES_RESUME_ID_STATUSES and self.resume_id is None:
            raise ValueError(
                f"resume_id must be set when status is '{self.status.value}'"
            )
        return self

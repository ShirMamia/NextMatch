"""
Dashboard metrics — Slice 9.

Pure computation module. No LLM, no I/O, no Streamlit.

Entry point:
  compute_summary(records) → ApplicationSummary

ApplicationSummary contains:
  - total record count
  - by_status: complete per-status counts for all ApplicationStatus values,
    using string enum-values as keys, in enum-definition order.
    All 9 statuses are always present (0 for any not seen in input).
  - direct count fields for the 6 core lifecycle statuses (UI convenience)
  - derived rate metrics (None when total == 0 to avoid division-by-zero)

Derived metric definitions:
  application_rate = (applied + interviewing + offered + rejected + withdrawn) / total
  active_pipeline  = tailored + applied + interviewing
  offer_rate       = offered / total
  rejection_rate   = rejected / total

All definitions are explicit and deterministic.
No status is ever silently dropped from by_status.
total always equals len(records).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.application import ApplicationRecord, ApplicationStatus

# Statuses that count as "applied or later" for application_rate.
# APPROVED is excluded: it is pre-application (resume ready, not yet submitted).
_APPLIED_OR_LATER: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
})

# Statuses that count as "active pipeline".
_ACTIVE_PIPELINE_STATUSES: frozenset[ApplicationStatus] = frozenset({
    ApplicationStatus.TAILORED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
})

# Canonical display order for by_status output — follows enum definition order.
_ALL_STATUSES: list[ApplicationStatus] = list(ApplicationStatus)


class ApplicationSummary(BaseModel):
    """Computed dashboard metrics for a collection of ApplicationRecords.

    by_status is always complete: every ApplicationStatus value appears as a
    string key (e.g. "tailored", "applied"), even if the count is 0.
    Keys follow enum-definition order.

    Direct count fields (count_tailored, count_applied, etc.) cover the 6
    core lifecycle statuses for convenient UI binding. Records with other
    statuses (DISCOVERED, SAVED, APPROVED) are captured only in by_status
    and the total count.
    """

    model_config = {"extra": "forbid"}

    total: int = 0

    # Complete per-status breakdown — all 9 statuses, string keys.
    by_status: dict[str, int] = Field(default_factory=dict)

    # Direct count fields for the 6 core UI statuses.
    count_tailored: int = 0
    count_applied: int = 0
    count_interviewing: int = 0
    count_offered: int = 0
    count_rejected: int = 0
    count_withdrawn: int = 0

    # Derived metrics — None when total == 0.
    active_pipeline: int = 0               # tailored + applied + interviewing
    application_rate: float | None = None  # applied_or_later / total
    offer_rate: float | None = None        # offered / total
    rejection_rate: float | None = None    # rejected / total


def compute_summary(records: list[ApplicationRecord]) -> ApplicationSummary:
    """Compute ApplicationSummary from a list of ApplicationRecords.

    Returns a zero-valued summary for an empty record list.
    All rate fields are None when total == 0.
    by_status always contains all 9 ApplicationStatus values.
    """
    total = len(records)

    # Count every record; initialise all statuses to 0 for completeness.
    raw_counts: dict[ApplicationStatus, int] = {s: 0 for s in _ALL_STATUSES}
    for record in records:
        raw_counts[record.status] = raw_counts.get(record.status, 0) + 1

    # Stable string-keyed output, enum-definition order.
    by_status: dict[str, int] = {s.value: raw_counts[s] for s in _ALL_STATUSES}

    if total == 0:
        return ApplicationSummary(by_status=by_status)

    def _n(status: ApplicationStatus) -> int:
        return raw_counts[status]

    count_tailored = _n(ApplicationStatus.TAILORED)
    count_applied = _n(ApplicationStatus.APPLIED)
    count_interviewing = _n(ApplicationStatus.INTERVIEWING)
    count_offered = _n(ApplicationStatus.OFFERED)
    count_rejected = _n(ApplicationStatus.REJECTED)
    count_withdrawn = _n(ApplicationStatus.WITHDRAWN)

    applied_or_later = sum(_n(s) for s in _APPLIED_OR_LATER)
    active = count_tailored + count_applied + count_interviewing

    return ApplicationSummary(
        total=total,
        by_status=by_status,
        count_tailored=count_tailored,
        count_applied=count_applied,
        count_interviewing=count_interviewing,
        count_offered=count_offered,
        count_rejected=count_rejected,
        count_withdrawn=count_withdrawn,
        active_pipeline=active,
        application_rate=applied_or_later / total,
        offer_rate=count_offered / total,
        rejection_rate=count_rejected / total,
    )

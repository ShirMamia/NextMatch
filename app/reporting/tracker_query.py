"""
Tracker query helpers — Slice 10.

Pure functions for filtering, sorting, and composing a tracker view.
No I/O, no Streamlit, no LLM.

Entry points:
  filter_records(records, query, status_filter) → list[ApplicationRecord]
  sort_records(records, sort_key)               → list[ApplicationRecord]
  apply_tracker_view(records, query, status_filter, sort_key)
                                                → list[ApplicationRecord]

sort_key values (use the named constants below):
  SORT_NEWEST           — created_at descending (default)
  SORT_OLDEST           — created_at ascending
  SORT_RECENTLY_UPDATED — updated_at descending
  SORT_APPLIED_AT       — applied_at descending, records without applied_at last
  SORT_STATUS           — status enum value, alphabetically

filter_records search behavior:
  - case-insensitive substring match
  - searches: application_id, job_id, candidate_id, status value, notes
  - empty or whitespace-only query matches all records
  - status_filter=None means no status restriction

apply_tracker_view composes filter → sort in one call so pages stay thin.
"""
from __future__ import annotations

from app.schemas.application import ApplicationRecord, ApplicationStatus

# ---------------------------------------------------------------------------
# Sort key constants — use these in UI code to avoid magic strings.
# ---------------------------------------------------------------------------

SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
SORT_RECENTLY_UPDATED = "recently_updated"
SORT_APPLIED_AT = "applied_at"
SORT_STATUS = "status"

# Ordered list of (sort_key, display_label) for UI selectbox binding.
SORT_OPTIONS: list[tuple[str, str]] = [
    (SORT_NEWEST, "Newest first"),
    (SORT_OLDEST, "Oldest first"),
    (SORT_RECENTLY_UPDATED, "Recently updated"),
    (SORT_APPLIED_AT, "Applied date (newest first)"),
    (SORT_STATUS, "Status (A–Z)"),
]


# ---------------------------------------------------------------------------
# filter_records
# ---------------------------------------------------------------------------

def filter_records(
    records: list[ApplicationRecord],
    query: str = "",
    status_filter: ApplicationStatus | None = None,
) -> list[ApplicationRecord]:
    """Return records matching both query and status_filter.

    Status filter is applied before text search so the search operates on the
    already-narrowed set.

    Args:
        records:       Input list. May be empty.
        query:         Substring to match (case-insensitive). Empty = no filter.
        status_filter: Exact ApplicationStatus to include. None = all statuses.

    Returns:
        Filtered list. Original list is not modified.
    """
    result = records

    if status_filter is not None:
        result = [r for r in result if r.status == status_filter]

    q = query.strip().lower()
    if q:
        result = [r for r in result if _matches_query(r, q)]

    return result


def _matches_query(record: ApplicationRecord, q: str) -> bool:
    """Return True if q appears in any searchable field of record.

    Builds a single lowercased string from all searchable fields and checks
    for substring containment. This keeps the match logic in one place and
    avoids repeating the lower() call per field.
    """
    searchable = " ".join([
        record.application_id,
        record.job_id,
        record.candidate_id,
        record.status.value,
        record.notes or "",
    ]).lower()
    return q in searchable


# ---------------------------------------------------------------------------
# sort_records
# ---------------------------------------------------------------------------

def sort_records(
    records: list[ApplicationRecord],
    sort_key: str = SORT_NEWEST,
) -> list[ApplicationRecord]:
    """Return a sorted copy of records according to sort_key.

    Unknown sort_key values fall back silently to SORT_NEWEST.

    SORT_APPLIED_AT: records with applied_at come first, newest applied_at
    first; records without applied_at come last.

    Args:
        records:  Input list. May be empty.
        sort_key: One of the SORT_* constants.

    Returns:
        New sorted list. Original list is not modified.
    """
    if sort_key == SORT_OLDEST:
        return sorted(records, key=lambda r: r.created_at)

    if sort_key == SORT_RECENTLY_UPDATED:
        return sorted(records, key=lambda r: r.updated_at, reverse=True)

    if sort_key == SORT_APPLIED_AT:
        with_date = [r for r in records if r.applied_at is not None]
        without_date = [r for r in records if r.applied_at is None]
        with_date = sorted(with_date, key=lambda r: r.applied_at, reverse=True)
        return with_date + without_date

    if sort_key == SORT_STATUS:
        return sorted(records, key=lambda r: r.status.value)

    # Default: SORT_NEWEST — created_at descending.
    return sorted(records, key=lambda r: r.created_at, reverse=True)


# ---------------------------------------------------------------------------
# apply_tracker_view — composed entry point
# ---------------------------------------------------------------------------

def apply_tracker_view(
    records: list[ApplicationRecord],
    query: str = "",
    status_filter: ApplicationStatus | None = None,
    sort_key: str = SORT_NEWEST,
) -> list[ApplicationRecord]:
    """Filter then sort records in one call.

    This is the single entry point that tracker_page.py calls so the page
    itself stays a thin UI shell.

    Args:
        records:       All application records from the tracker service.
        query:         Free-text search string.
        status_filter: Status to include, or None for all statuses.
        sort_key:      One of the SORT_* constants.

    Returns:
        Filtered and sorted list ready for display.
    """
    filtered = filter_records(records, query=query, status_filter=status_filter)
    return sort_records(filtered, sort_key=sort_key)

"""
Application Tracker page — Slice 10 (updated from Slice 8).

Displays all saved ApplicationRecords with search, filter, sort, and notes
editing. Status updates and notes updates both persist through TrackerService.

Page structure:
  1. Load all application records via TrackerService.
  2. Show an empty-state message if no records exist.
  3. Render search / filter / sort controls.
  4. Apply controls via apply_tracker_view() (pure helper, no UI logic).
  5. Show count of matching records.
  6. For each visible record, render info, status update, and notes editing.

Search behavior:
  - Case-insensitive substring match over application_id, job_id,
    candidate_id, status value, and notes.
  - Empty search shows all records.

Filter behavior:
  - "All statuses" shows every record regardless of status.
  - Selecting a specific status restricts to that status only.
  - Filter options cover all 9 real ApplicationStatus values.

Sort behavior:
  - Five sort options: newest, oldest, recently updated, applied date, status.
  - Sort is applied after filter.

Status update behavior:
  - All 9 ApplicationStatus values are available as update targets.
  - The selectbox always shows the record's true current status, regardless of
    which status it holds. No fallback to a wrong default.
  - applied_at is set/cleared automatically by TrackerService.
  - Schema constraint failures (e.g. moving to APPROVED without a resume_id)
    are caught and shown as user-visible errors rather than crashing.

Notes editing:
  - Text area pre-filled with current notes.
  - "Save notes" persists through TrackerService.update_notes().
  - Notes save does not rerun the page; success is shown inline.

All persistence delegates to TrackerService.
All filtering/sorting delegates to apply_tracker_view from tracker_query.
This file is a thin UI shell only — no business logic lives here.
"""
from __future__ import annotations

from pydantic import ValidationError
import streamlit as st

from app.reporting.tracker import TrackerService
from app.reporting.tracker_query import (
    SORT_NEWEST,
    SORT_OPTIONS,
    apply_tracker_view,
)
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.services.config import get_config
from app.storage.file_store import FileStore
from app.utils.time import format_date

# Human-readable labels for ALL 9 ApplicationStatus values.
# Used in both the status-update selectbox and the filter selectbox.
_STATUS_LABEL: dict[ApplicationStatus, str] = {
    ApplicationStatus.DISCOVERED:  "Discovered",
    ApplicationStatus.SAVED:       "Saved",
    ApplicationStatus.TAILORED:    "Tailored",
    ApplicationStatus.APPROVED:    "Approved",
    ApplicationStatus.APPLIED:     "Applied",
    ApplicationStatus.INTERVIEWING: "Interviewing",
    ApplicationStatus.OFFERED:     "Offer received",
    ApplicationStatus.REJECTED:    "Rejected",
    ApplicationStatus.WITHDRAWN:   "Withdrawn",
}

# All 9 statuses, in enum-definition order, for the status-update selectbox.
_ALL_STATUS_OPTIONS: list[ApplicationStatus] = list(ApplicationStatus)

# "All" sentinel value for the status filter selectbox.
_ALL_STATUSES = "all"


def render() -> None:
    st.header("Application Tracker")
    st.caption(
        "Track the status of your saved applications. "
        "Search, filter, and sort your records. "
        "Update status or notes on any record."
    )

    cfg = get_config()
    store = FileStore(cfg.data_dir)
    tracker = TrackerService(store)

    records = tracker.list_applications()

    if not records:
        st.info(
            "No saved applications yet. "
            "Go to **Tailoring Studio**, generate and validate a resume, "
            "then click **Approve and Save** to create your first record."
        )
        return

    # --- Controls: search / filter / sort ---
    query, status_filter, sort_key = _render_controls()

    # Delegate all view logic to the pure helper.
    visible = apply_tracker_view(
        records,
        query=query,
        status_filter=status_filter,
        sort_key=sort_key,
    )

    total = len(records)
    shown = len(visible)
    if shown == total:
        st.markdown(f"**{total} application{'s' if total != 1 else ''}**")
    else:
        st.markdown(f"**{shown} of {total} application{'s' if total != 1 else ''} shown**")

    st.divider()

    if not visible:
        st.info("No records match the current search and filter.")
        return

    for record in visible:
        _render_record(record, tracker)


def _render_controls() -> tuple[str, ApplicationStatus | None, str]:
    """Render search, filter, and sort controls. Returns (query, status_filter, sort_key)."""
    col_search, col_filter, col_sort = st.columns([3, 2, 2])

    with col_search:
        query = st.text_input(
            "Search",
            value="",
            placeholder="Search by ID, job, status, notes…",
            key="tracker_search",
            label_visibility="collapsed",
        )

    # Build filter options: "All" sentinel + every real ApplicationStatus.
    filter_keys = [_ALL_STATUSES] + [s.value for s in ApplicationStatus]
    filter_labels = {_ALL_STATUSES: "All statuses"}
    for s in ApplicationStatus:
        filter_labels[s.value] = _STATUS_LABEL.get(s, s.value)

    with col_filter:
        selected_filter = st.selectbox(
            "Status filter",
            options=filter_keys,
            format_func=lambda k: filter_labels.get(k, k),
            key="tracker_status_filter",
            label_visibility="collapsed",
        )

    status_filter: ApplicationStatus | None = None
    if selected_filter != _ALL_STATUSES:
        try:
            status_filter = ApplicationStatus(selected_filter)
        except ValueError:
            status_filter = None

    # Sort selectbox.
    sort_keys = [k for k, _ in SORT_OPTIONS]
    sort_labels = {k: label for k, label in SORT_OPTIONS}

    with col_sort:
        sort_key = st.selectbox(
            "Sort by",
            options=sort_keys,
            format_func=lambda k: sort_labels[k],
            index=sort_keys.index(SORT_NEWEST),
            key="tracker_sort_key",
            label_visibility="collapsed",
        )

    return query, status_filter, sort_key


def _render_record(record: ApplicationRecord, tracker: TrackerService) -> None:
    """Render a single ApplicationRecord with status update and notes editing."""
    job_label = _resolve_job_label(record.job_id)
    current_label = _STATUS_LABEL.get(record.status, record.status.value)
    expander_title = f"{job_label} — {current_label}"

    with st.expander(expander_title, expanded=False):
        col_info, col_action = st.columns([2, 1])

        with col_info:
            st.caption(f"Application ID: `{record.application_id[:8]}\u2026`")
            st.caption(f"Job ID: `{record.job_id[:8]}\u2026`")
            st.caption(f"Candidate ID: `{record.candidate_id[:8]}\u2026`")
            st.caption(f"Created: {format_date(record.created_at)}")
            st.caption(f"Updated: {format_date(record.updated_at)}")
            if record.applied_at is not None:
                st.caption(f"Applied: {format_date(record.applied_at)}")

        with col_action:
            _render_status_update(record, tracker)

        st.divider()
        _render_notes_editor(record, tracker)


def _render_status_update(record: ApplicationRecord, tracker: TrackerService) -> None:
    """Render the status selectbox and Save button for one record.

    Uses all 9 ApplicationStatus values so the selectbox always reflects the
    record's true current status — no silent fallback to an incorrect default.
    """
    st.markdown("**Update status**")

    # Since _ALL_STATUS_OPTIONS contains every ApplicationStatus value, this
    # index() call will always succeed without a try/except fallback.
    current_idx = _ALL_STATUS_OPTIONS.index(record.status)

    new_status = st.selectbox(
        "Status",
        options=_ALL_STATUS_OPTIONS,
        index=current_idx,
        format_func=lambda s: _STATUS_LABEL.get(s, s.value),
        key=f"status_select_{record.application_id}",
        label_visibility="collapsed",
    )

    if st.button("Save status", key=f"save_status_{record.application_id}"):
        if new_status == record.status:
            st.info("Status unchanged.")
        else:
            try:
                tracker.update_status(record.application_id, new_status)
                st.success(
                    f"Status updated to **{_STATUS_LABEL.get(new_status, new_status.value)}**."
                )
                st.rerun()
            except ValidationError as exc:
                st.error(f"Invalid status transition: {exc.errors()[0]['msg']}")
            except ValueError as exc:
                st.error(f"Update failed: {exc}")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")


def _render_notes_editor(record: ApplicationRecord, tracker: TrackerService) -> None:
    """Render the notes text area and Save notes button for one record."""
    st.markdown("**Notes**")

    notes_value = st.text_area(
        "Notes",
        value=record.notes or "",
        placeholder="Add notes about this application…",
        key=f"notes_area_{record.application_id}",
        label_visibility="collapsed",
        height=80,
    )

    if st.button("Save notes", key=f"save_notes_{record.application_id}"):
        try:
            tracker.update_notes(record.application_id, notes_value)
            st.success("Notes saved.")
        except ValueError as exc:
            st.error(f"Notes update failed: {exc}")
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")


def _resolve_job_label(job_id: str) -> str:
    """Return a human-readable job label from the in-session job list.

    Falls back to a truncated job_id. Best-effort — the tracker stores job_id,
    not the full job posting.
    """
    job_postings = st.session_state.get("job_postings") or []
    for job in job_postings:
        if getattr(job, "job_id", None) == job_id:
            return f"{job.title} at {job.company}"
    return f"Job {job_id[:8]}\u2026"

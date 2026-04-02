"""
Application Tracker page — Slice 8.

Displays all saved ApplicationRecords and allows manual status updates.

Page structure:
  1. Load all application records from the storage layer via TrackerService.
  2. Show an empty-state message if no records exist.
  3. For each record, show key fields and a status selectbox.
  4. Persist status changes through the TrackerService.

Status update behavior:
  - applied_at is set automatically by TrackerService when moving to APPLIED
    or any later requiring-applied-at status.
  - applied_at is cleared automatically when reverting to a pre-application status.
  - Validation or generation state is not affected by tracker status changes.

Available statuses in the UI (covers the core candidate lifecycle):
  tailored → applied → interviewing → offered → rejected / withdrawn

Dashboard metrics and export are NOT implemented here — that is Slice 9.

All persistence logic delegates to TrackerService and the storage layer.
This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.services.config import get_config
from app.storage.file_store import FileStore
from app.utils.time import format_date

# Statuses shown in the tracker UI and their display labels.
_STATUS_OPTIONS: list[ApplicationStatus] = [
    ApplicationStatus.TAILORED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
]

_STATUS_LABEL: dict[ApplicationStatus, str] = {
    ApplicationStatus.TAILORED: "Tailored",
    ApplicationStatus.APPLIED: "Applied",
    ApplicationStatus.INTERVIEWING: "Interviewing",
    ApplicationStatus.OFFERED: "Offer received",
    ApplicationStatus.REJECTED: "Rejected",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}


def render() -> None:
    st.header("Application Tracker")
    st.caption(
        "Track the status of your saved applications. "
        "Use the status selector on each record to update your progress."
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

    st.markdown(f"**{len(records)} application{'s' if len(records) != 1 else ''}**")
    st.divider()

    for record in records:
        _render_record(record, tracker)


def _render_record(record: ApplicationRecord, tracker: TrackerService) -> None:
    """Render a single ApplicationRecord with its status update control."""
    # Best-effort job title lookup from session state (jobs in-memory this session).
    job_label = _resolve_job_label(record.job_id)

    # Expander title: job label + current status
    current_label = _STATUS_LABEL.get(record.status, record.status.value)
    expander_title = f"{job_label} — {current_label}"

    with st.expander(expander_title, expanded=False):
        col_info, col_action = st.columns([2, 1])

        with col_info:
            st.caption(f"Application ID: `{record.application_id[:8]}\u2026`")
            st.caption(f"Job ID: `{record.job_id[:8]}\u2026`")
            st.caption(f"Candidate ID: `{record.candidate_id[:8]}\u2026`")
            st.caption(f"Created: {format_date(record.created_at)}")
            if record.applied_at is not None:
                st.caption(f"Applied: {format_date(record.applied_at)}")
            if record.notes:
                st.markdown(f"**Notes:** {record.notes}")

        with col_action:
            st.markdown("**Update status**")
            # Determine current index for the selectbox default.
            try:
                current_idx = _STATUS_OPTIONS.index(record.status)
            except ValueError:
                current_idx = 0

            new_status = st.selectbox(
                "Status",
                options=_STATUS_OPTIONS,
                index=current_idx,
                format_func=lambda s: _STATUS_LABEL.get(s, s.value),
                key=f"status_select_{record.application_id}",
                label_visibility="collapsed",
            )

            if st.button("Save", key=f"save_status_{record.application_id}"):
                if new_status == record.status:
                    st.info("Status unchanged.")
                else:
                    try:
                        tracker.update_status(record.application_id, new_status)
                        st.success(
                            f"Status updated to **{_STATUS_LABEL.get(new_status, new_status.value)}**."
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"Update failed: {exc}")
                    except Exception as exc:
                        st.error(f"Unexpected error: {exc}")


def _resolve_job_label(job_id: str) -> str:
    """Return a human-readable job label by looking up the in-session job list.

    Falls back to a truncated job_id if the job is not in session state.
    This is a best-effort lookup — the tracker stores job_id, not the full job.
    """
    job_postings = st.session_state.get("job_postings") or []
    for job in job_postings:
        if getattr(job, "job_id", None) == job_id:
            return f"{job.title} at {job.company}"
    return f"Job {job_id[:8]}\u2026"

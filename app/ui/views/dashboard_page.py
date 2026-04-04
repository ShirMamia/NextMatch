"""
Dashboard page — Slice 9.

Displays computed metrics from all saved ApplicationRecords and provides
an XLSX export button.

Page structure:
  1. Load all ApplicationRecords via TrackerService.
  2. Compute summary via compute_summary().
  3. Show headline KPIs (total, active pipeline, rates).
  4. Show per-status breakdown.
  5. Offer XLSX export via st.download_button (in-memory, no temp file).

All computation delegates to app.reporting.dashboard and app.reporting.exporter.
This file is a thin UI shell only — no business logic lives here.
"""
from __future__ import annotations

import io

import streamlit as st

from app.reporting.dashboard import compute_summary
from app.reporting.exporter import export_to_xlsx, records_to_rows
from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationStatus
from app.services.config import get_config
from app.storage.file_store import FileStore

# Human-readable labels for each status, used in the breakdown table.
_STATUS_LABEL: dict[ApplicationStatus, str] = {
    ApplicationStatus.DISCOVERED: "Discovered",
    ApplicationStatus.SAVED: "Saved",
    ApplicationStatus.TAILORED: "Tailored",
    ApplicationStatus.APPROVED: "Approved",
    ApplicationStatus.APPLIED: "Applied",
    ApplicationStatus.INTERVIEWING: "Interviewing",
    ApplicationStatus.OFFERED: "Offer received",
    ApplicationStatus.REJECTED: "Rejected",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}


def render() -> None:
    st.header("Dashboard")
    st.caption("Application funnel metrics across all saved records.")

    cfg = get_config()
    store = FileStore(cfg.data_dir)
    tracker = TrackerService(store)

    records = tracker.list_applications()
    summary = compute_summary(records)

    if not records:
        st.info(
            "No saved applications yet. "
            "Go to **Tailoring Studio**, generate and validate a resume, "
            "then click **Approve and Save** to create your first record."
        )
        return

    # --- Headline KPIs ---
    st.subheader("Overview")
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Total applications", summary.total)
    col2.metric("Active pipeline", summary.active_pipeline)

    def _pct(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value * 100:.0f}%"

    col3.metric("Application rate", _pct(summary.application_rate))
    col4.metric("Offer rate", _pct(summary.offer_rate))
    col5.metric("Rejection rate", _pct(summary.rejection_rate))

    st.divider()

    # --- Per-status breakdown ---
    st.subheader("Status breakdown")

    breakdown_rows = []
    for status in ApplicationStatus:
        count = summary.by_status.get(status.value, 0)
        label = _STATUS_LABEL.get(status, status.value)
        breakdown_rows.append({"Status": label, "Count": count})

    # Display as a compact table using columns.
    for row in breakdown_rows:
        c_label, c_count = st.columns([3, 1])
        c_label.write(row["Status"])
        c_count.write(str(row["Count"]))

    st.divider()

    # --- Export ---
    st.subheader("Export")

    xlsx_bytes = _build_xlsx_bytes(records)
    st.download_button(
        label="Download tracker as XLSX",
        data=xlsx_bytes,
        file_name="nextmatch_tracker.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _build_xlsx_bytes(records) -> bytes:
    """Build XLSX export in memory and return as bytes for st.download_button."""
    buf = io.BytesIO()
    export_to_xlsx(records, buf)
    buf.seek(0)
    return buf.read()

"""
Application tracker exporter — Slice 9.

Pure computation module. No LLM, no I/O beyond writing the XLSX file, no Streamlit.

Entry points:
  records_to_rows(records) → list[dict]
  export_to_xlsx(records, path) → None

Output format (XLSX, two sheets):
  Sheet 1 — "Applications"
    One row per ApplicationRecord. Columns:
      application_id, job_id, candidate_id, resume_id, status,
      created_at, updated_at, applied_at, notes

  Sheet 2 — "Summary"
    Computed metrics from compute_summary(). Two-column key/value layout.
    Rows (in order):
      Total Applications, Active Pipeline, Application Rate (%),
      Offer Rate (%), Rejection Rate (%), then one row per status count.

Datetime columns in Sheet 1 are ISO-8601 strings (UTC). This avoids timezone
serialization issues across Excel versions and platforms.

records_to_rows() is a pure dict-serializer — suitable for testing and reuse.
export_to_xlsx() is the only function that touches the filesystem.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.reporting.dashboard import compute_summary
from app.schemas.application import ApplicationRecord, ApplicationStatus


def records_to_rows(records: list[ApplicationRecord]) -> list[dict]:
    """Serialize ApplicationRecords to plain dicts suitable for DataFrame construction.

    Datetimes are converted to ISO-8601 strings. None values are preserved as None
    (pandas will render them as empty cells).

    Returns an empty list for an empty input.
    """
    rows = []
    for r in records:
        rows.append(
            {
                "application_id": r.application_id,
                "job_id": r.job_id,
                "candidate_id": r.candidate_id,
                "resume_id": r.resume_id,
                "status": r.status.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "notes": r.notes,
            }
        )
    return rows


def export_to_xlsx(records: list[ApplicationRecord], path: str | Path) -> None:
    """Export ApplicationRecords to a two-sheet XLSX file.

    Sheet 1 — Applications: one row per record (via records_to_rows).
    Sheet 2 — Summary: key/value metric rows from compute_summary.

    Args:
        records: List of ApplicationRecords to export. May be empty.
        path:    Destination file path. Parent directory must exist.

    Raises:
        OSError: if the file cannot be written (permissions, missing parent).
    """
    summary = compute_summary(records)

    # --- Sheet 1: Applications ---
    rows = records_to_rows(records)
    df_apps = pd.DataFrame(
        rows,
        columns=[
            "application_id",
            "job_id",
            "candidate_id",
            "resume_id",
            "status",
            "created_at",
            "updated_at",
            "applied_at",
            "notes",
        ],
    )

    # --- Sheet 2: Summary (key/value) ---
    def _pct(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value * 100:.1f}%"

    summary_rows: list[dict[str, object]] = [
        {"Metric": "Total Applications", "Value": summary.total},
        {"Metric": "Active Pipeline", "Value": summary.active_pipeline},
        {"Metric": "Application Rate", "Value": _pct(summary.application_rate)},
        {"Metric": "Offer Rate", "Value": _pct(summary.offer_rate)},
        {"Metric": "Rejection Rate", "Value": _pct(summary.rejection_rate)},
    ]
    # One row per status, in enum-definition order.
    for status in ApplicationStatus:
        count = summary.by_status.get(status.value, 0)
        summary_rows.append(
            {"Metric": f"Status: {status.value}", "Value": count}
        )

    df_summary = pd.DataFrame(summary_rows, columns=["Metric", "Value"])

    # --- Write XLSX ---
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_apps.to_excel(writer, sheet_name="Applications", index=False)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)

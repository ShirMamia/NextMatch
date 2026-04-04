"""
Tests for Slice 9 dashboard and export modules.

Covers:
  - compute_summary: empty input, counts, derived metrics, by_status completeness
  - records_to_rows: field mapping, datetime serialization, None handling
  - export_to_xlsx: file creation, sheet names, row counts, column presence
"""
from __future__ import annotations

import openpyxl
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reporting.dashboard import ApplicationSummary, compute_summary
from app.reporting.exporter import export_to_xlsx, records_to_rows
from app.schemas.application import ApplicationRecord, ApplicationStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _make_record(
    status: ApplicationStatus,
    application_id: str = "app1",
    job_id: str = "job1",
    candidate_id: str = "cand1",
    resume_id: str | None = None,
    applied_at: datetime | None = None,
    notes: str = "",
) -> ApplicationRecord:
    """Create a minimal valid ApplicationRecord for testing."""
    # Set applied_at for statuses that require it.
    _requires_applied_at = {
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
    if status in _requires_applied_at and applied_at is None:
        applied_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=_UTC)

    # Set resume_id for statuses that require it.
    _requires_resume_id = {
        ApplicationStatus.APPROVED,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
    if status in _requires_resume_id and resume_id is None:
        resume_id = "resume_test"

    return ApplicationRecord(
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        resume_id=resume_id,
        status=status,
        applied_at=applied_at,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# compute_summary — empty input
# ---------------------------------------------------------------------------


class TestComputeSummaryEmpty:
    def test_returns_application_summary(self):
        result = compute_summary([])
        assert isinstance(result, ApplicationSummary)

    def test_total_is_zero(self):
        result = compute_summary([])
        assert result.total == 0

    def test_all_counts_are_zero(self):
        result = compute_summary([])
        assert result.count_tailored == 0
        assert result.count_applied == 0
        assert result.count_interviewing == 0
        assert result.count_offered == 0
        assert result.count_rejected == 0
        assert result.count_withdrawn == 0
        assert result.active_pipeline == 0

    def test_rates_are_none(self):
        result = compute_summary([])
        assert result.application_rate is None
        assert result.offer_rate is None
        assert result.rejection_rate is None

    def test_by_status_contains_all_nine_statuses(self):
        result = compute_summary([])
        assert len(result.by_status) == 9
        for status in ApplicationStatus:
            assert status.value in result.by_status

    def test_by_status_all_zeros_on_empty(self):
        result = compute_summary([])
        for count in result.by_status.values():
            assert count == 0

    def test_by_status_uses_string_keys(self):
        result = compute_summary([])
        for key in result.by_status:
            assert isinstance(key, str)


# ---------------------------------------------------------------------------
# compute_summary — counts by status
# ---------------------------------------------------------------------------


class TestComputeSummaryCounts:
    def _records(self) -> list[ApplicationRecord]:
        return [
            _make_record(ApplicationStatus.TAILORED, application_id="a1"),
            _make_record(ApplicationStatus.TAILORED, application_id="a2"),
            _make_record(ApplicationStatus.APPLIED, application_id="a3"),
            _make_record(ApplicationStatus.INTERVIEWING, application_id="a4"),
            _make_record(ApplicationStatus.OFFERED, application_id="a5"),
            _make_record(ApplicationStatus.REJECTED, application_id="a6"),
            _make_record(ApplicationStatus.WITHDRAWN, application_id="a7"),
        ]

    def test_total_equals_len_records(self):
        records = self._records()
        result = compute_summary(records)
        assert result.total == len(records)

    def test_count_tailored(self):
        result = compute_summary(self._records())
        assert result.count_tailored == 2

    def test_count_applied(self):
        result = compute_summary(self._records())
        assert result.count_applied == 1

    def test_count_interviewing(self):
        result = compute_summary(self._records())
        assert result.count_interviewing == 1

    def test_count_offered(self):
        result = compute_summary(self._records())
        assert result.count_offered == 1

    def test_count_rejected(self):
        result = compute_summary(self._records())
        assert result.count_rejected == 1

    def test_count_withdrawn(self):
        result = compute_summary(self._records())
        assert result.count_withdrawn == 1

    def test_by_status_counts_match_direct_fields(self):
        result = compute_summary(self._records())
        assert result.by_status["tailored"] == result.count_tailored
        assert result.by_status["applied"] == result.count_applied
        assert result.by_status["interviewing"] == result.count_interviewing
        assert result.by_status["offered"] == result.count_offered
        assert result.by_status["rejected"] == result.count_rejected
        assert result.by_status["withdrawn"] == result.count_withdrawn

    def test_by_status_unseen_statuses_are_zero(self):
        result = compute_summary(self._records())
        assert result.by_status["discovered"] == 0
        assert result.by_status["saved"] == 0
        assert result.by_status["approved"] == 0

    def test_active_pipeline(self):
        # tailored(2) + applied(1) + interviewing(1) = 4
        result = compute_summary(self._records())
        assert result.active_pipeline == 4

    def test_single_record_total(self):
        result = compute_summary([_make_record(ApplicationStatus.TAILORED)])
        assert result.total == 1


# ---------------------------------------------------------------------------
# compute_summary — derived rates
# ---------------------------------------------------------------------------


class TestComputeSummaryRates:
    def _uniform_records(self) -> list[ApplicationRecord]:
        """4 records: 1 applied, 1 offered, 1 rejected, 1 tailored."""
        return [
            _make_record(ApplicationStatus.APPLIED, application_id="r1"),
            _make_record(ApplicationStatus.OFFERED, application_id="r2"),
            _make_record(ApplicationStatus.REJECTED, application_id="r3"),
            _make_record(ApplicationStatus.TAILORED, application_id="r4"),
        ]

    def test_application_rate_non_none_when_total_gt_zero(self):
        result = compute_summary(self._uniform_records())
        assert result.application_rate is not None

    def test_offer_rate_non_none_when_total_gt_zero(self):
        result = compute_summary(self._uniform_records())
        assert result.offer_rate is not None

    def test_rejection_rate_non_none_when_total_gt_zero(self):
        result = compute_summary(self._uniform_records())
        assert result.rejection_rate is not None

    def test_application_rate_value(self):
        # applied_or_later = applied(1) + offered(1) + rejected(1) = 3; total = 4
        result = compute_summary(self._uniform_records())
        assert abs(result.application_rate - 3 / 4) < 1e-9

    def test_offer_rate_value(self):
        # offered(1) / total(4)
        result = compute_summary(self._uniform_records())
        assert abs(result.offer_rate - 1 / 4) < 1e-9

    def test_rejection_rate_value(self):
        # rejected(1) / total(4)
        result = compute_summary(self._uniform_records())
        assert abs(result.rejection_rate - 1 / 4) < 1e-9

    def test_application_rate_all_tailored(self):
        # applied_or_later = 0 → rate = 0.0
        records = [
            _make_record(ApplicationStatus.TAILORED, application_id=f"t{i}")
            for i in range(3)
        ]
        result = compute_summary(records)
        assert result.application_rate == 0.0

    def test_offer_rate_zero_when_no_offers(self):
        records = [_make_record(ApplicationStatus.APPLIED, application_id="x")]
        result = compute_summary(records)
        assert result.offer_rate == 0.0

    def test_rates_are_floats_when_not_none(self):
        result = compute_summary(self._uniform_records())
        assert isinstance(result.application_rate, float)
        assert isinstance(result.offer_rate, float)
        assert isinstance(result.rejection_rate, float)


# ---------------------------------------------------------------------------
# compute_summary — by_status ordering
# ---------------------------------------------------------------------------


class TestComputeSummaryByStatusOrder:
    def test_keys_in_enum_definition_order(self):
        records = [
            _make_record(ApplicationStatus.REJECTED, application_id="r1"),
            _make_record(ApplicationStatus.TAILORED, application_id="r2"),
        ]
        result = compute_summary(records)
        expected_order = [s.value for s in ApplicationStatus]
        assert list(result.by_status.keys()) == expected_order

    def test_empty_input_keys_in_enum_definition_order(self):
        result = compute_summary([])
        expected_order = [s.value for s in ApplicationStatus]
        assert list(result.by_status.keys()) == expected_order


# ---------------------------------------------------------------------------
# records_to_rows
# ---------------------------------------------------------------------------


class TestRecordsToRows:
    def test_empty_input_returns_empty_list(self):
        assert records_to_rows([]) == []

    def test_returns_one_row_per_record(self):
        records = [
            _make_record(ApplicationStatus.TAILORED, application_id="a1"),
            _make_record(ApplicationStatus.APPLIED, application_id="a2"),
        ]
        rows = records_to_rows(records)
        assert len(rows) == 2

    def test_status_serialized_as_string(self):
        record = _make_record(ApplicationStatus.TAILORED)
        row = records_to_rows([record])[0]
        assert row["status"] == "tailored"
        assert isinstance(row["status"], str)

    def test_application_id_present(self):
        record = _make_record(ApplicationStatus.TAILORED, application_id="abc123")
        row = records_to_rows([record])[0]
        assert row["application_id"] == "abc123"

    def test_job_id_present(self):
        record = _make_record(ApplicationStatus.TAILORED, job_id="job_xyz")
        row = records_to_rows([record])[0]
        assert row["job_id"] == "job_xyz"

    def test_applied_at_none_when_no_applied_at(self):
        record = _make_record(ApplicationStatus.TAILORED)
        row = records_to_rows([record])[0]
        assert row["applied_at"] is None

    def test_applied_at_iso_string_when_set(self):
        dt = datetime(2026, 2, 10, 14, 30, 0, tzinfo=_UTC)
        record = _make_record(ApplicationStatus.APPLIED, applied_at=dt)
        row = records_to_rows([record])[0]
        assert isinstance(row["applied_at"], str)
        assert "2026-02-10" in row["applied_at"]

    def test_created_at_is_iso_string(self):
        record = _make_record(ApplicationStatus.TAILORED)
        row = records_to_rows([record])[0]
        assert isinstance(row["created_at"], str)

    def test_resume_id_none_when_not_set(self):
        record = _make_record(ApplicationStatus.TAILORED)
        row = records_to_rows([record])[0]
        assert row["resume_id"] is None

    def test_notes_present(self):
        record = _make_record(ApplicationStatus.TAILORED, notes="follow up Monday")
        row = records_to_rows([record])[0]
        assert row["notes"] == "follow up Monday"

    def test_all_expected_keys_present(self):
        record = _make_record(ApplicationStatus.TAILORED)
        row = records_to_rows([record])[0]
        expected_keys = {
            "application_id", "job_id", "candidate_id", "resume_id",
            "status", "created_at", "updated_at", "applied_at", "notes",
        }
        assert set(row.keys()) == expected_keys


# ---------------------------------------------------------------------------
# export_to_xlsx
# ---------------------------------------------------------------------------


class TestExportToXlsx:
    def _sample_records(self) -> list[ApplicationRecord]:
        return [
            _make_record(ApplicationStatus.TAILORED, application_id="e1"),
            _make_record(ApplicationStatus.APPLIED, application_id="e2"),
            _make_record(ApplicationStatus.OFFERED, application_id="e3"),
        ]

    def test_creates_file(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        assert out.exists()

    def test_has_applications_sheet(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        assert "Applications" in wb.sheetnames

    def test_has_summary_sheet(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        assert "Summary" in wb.sheetnames

    def test_applications_sheet_row_count(self, tmp_path: Path):
        records = self._sample_records()
        out = tmp_path / "export.xlsx"
        export_to_xlsx(records, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Applications"]
        # 1 header + N data rows
        assert ws.max_row == len(records) + 1

    def test_applications_sheet_has_status_column(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Applications"]
        headers = [cell.value for cell in ws[1]]
        assert "status" in headers

    def test_applications_sheet_has_application_id_column(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Applications"]
        headers = [cell.value for cell in ws[1]]
        assert "application_id" in headers

    def test_summary_sheet_has_metric_and_value_columns(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Summary"]
        headers = [cell.value for cell in ws[1]]
        assert "Metric" in headers
        assert "Value" in headers

    def test_summary_sheet_contains_total_applications_row(self, tmp_path: Path):
        out = tmp_path / "export.xlsx"
        export_to_xlsx(self._sample_records(), out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Summary"]
        metrics = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
        assert "Total Applications" in metrics

    def test_empty_records_creates_valid_file(self, tmp_path: Path):
        out = tmp_path / "empty_export.xlsx"
        export_to_xlsx([], out)
        assert out.exists()
        wb = openpyxl.load_workbook(out)
        assert "Applications" in wb.sheetnames
        assert "Summary" in wb.sheetnames

    def test_empty_records_applications_sheet_header_only(self, tmp_path: Path):
        out = tmp_path / "empty_export.xlsx"
        export_to_xlsx([], out)
        wb = openpyxl.load_workbook(out)
        ws = wb["Applications"]
        # Header row only — no data rows.
        assert ws.max_row == 1

    def test_accepts_path_object(self, tmp_path: Path):
        out = tmp_path / "path_obj.xlsx"
        export_to_xlsx(self._sample_records(), out)  # Path object, not str
        assert out.exists()

    def test_accepts_string_path(self, tmp_path: Path):
        out = tmp_path / "str_path.xlsx"
        export_to_xlsx(self._sample_records(), str(out))  # str, not Path
        assert out.exists()

"""
Tests for Slice 10 tracker query helpers.

Covers:
  - filter_records: text search, status filter, combined, empty input
  - sort_records: all 5 sort keys, SORT_APPLIED_AT correctness, unknown key fallback
  - apply_tracker_view: composed filter + sort
  - TrackerService.update_notes: persistence contract
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.reporting.tracker_query import (
    SORT_APPLIED_AT,
    SORT_NEWEST,
    SORT_OLDEST,
    SORT_RECENTLY_UPDATED,
    SORT_STATUS,
    apply_tracker_view,
    filter_records,
    sort_records,
)
from app.schemas.application import ApplicationRecord, ApplicationStatus

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(
    application_id: str,
    status: ApplicationStatus = ApplicationStatus.TAILORED,
    job_id: str = "job1",
    candidate_id: str = "cand1",
    notes: str = "",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    applied_at: datetime | None = None,
    resume_id: str | None = None,
) -> ApplicationRecord:
    _requires_applied = {
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
    _requires_resume = {
        ApplicationStatus.APPROVED,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }
    if status in _requires_applied and applied_at is None:
        applied_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=_UTC)
    if status in _requires_resume and resume_id is None:
        resume_id = "resume_test"

    kwargs: dict = dict(
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        status=status,
        notes=notes,
        resume_id=resume_id,
        applied_at=applied_at,
    )
    record = ApplicationRecord(**kwargs)
    # Override timestamps via model_dump + model_validate to bypass default_factory.
    if created_at is not None or updated_at is not None:
        data = record.model_dump(mode="json")
        if created_at is not None:
            data["created_at"] = created_at.isoformat()
        if updated_at is not None:
            data["updated_at"] = updated_at.isoformat()
        record = ApplicationRecord.model_validate(data)
    return record


# ---------------------------------------------------------------------------
# filter_records — empty input
# ---------------------------------------------------------------------------

class TestFilterRecordsEmpty:
    def test_empty_input_returns_empty(self):
        assert filter_records([]) == []

    def test_empty_input_with_query_returns_empty(self):
        assert filter_records([], query="anything") == []

    def test_empty_input_with_status_filter_returns_empty(self):
        assert filter_records([], status_filter=ApplicationStatus.TAILORED) == []


# ---------------------------------------------------------------------------
# filter_records — text search
# ---------------------------------------------------------------------------

class TestFilterRecordsTextSearch:
    def _records(self) -> list[ApplicationRecord]:
        return [
            _rec("app-alpha", job_id="job-python", candidate_id="cand1"),
            _rec("app-beta",  job_id="job-java",   candidate_id="cand2"),
            _rec("app-gamma", job_id="job-rust",    candidate_id="cand3"),
        ]

    def test_no_query_returns_all(self):
        records = self._records()
        assert filter_records(records, query="") == records

    def test_whitespace_query_returns_all(self):
        records = self._records()
        assert filter_records(records, query="   ") == records

    def test_match_on_application_id(self):
        records = self._records()
        result = filter_records(records, query="alpha")
        assert len(result) == 1
        assert result[0].application_id == "app-alpha"

    def test_match_on_job_id(self):
        records = self._records()
        result = filter_records(records, query="python")
        assert len(result) == 1
        assert result[0].job_id == "job-python"

    def test_match_on_candidate_id(self):
        records = self._records()
        result = filter_records(records, query="cand2")
        assert len(result) == 1
        assert result[0].candidate_id == "cand2"

    def test_match_on_status_value(self):
        records = self._records()
        result = filter_records(records, query="tailored")
        assert len(result) == 3  # all records are TAILORED

    def test_match_on_notes(self):
        records = [
            _rec("a1", notes="follow up next week"),
            _rec("a2", notes="waiting for response"),
        ]
        result = filter_records(records, query="follow")
        assert len(result) == 1
        assert result[0].application_id == "a1"

    def test_case_insensitive_match(self):
        records = self._records()
        result = filter_records(records, query="ALPHA")
        assert len(result) == 1
        assert result[0].application_id == "app-alpha"

    def test_no_match_returns_empty(self):
        records = self._records()
        assert filter_records(records, query="zzz_no_match") == []

    def test_partial_match(self):
        records = self._records()
        # "app" appears in all three application_ids
        result = filter_records(records, query="app")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# filter_records — status filter
# ---------------------------------------------------------------------------

class TestFilterRecordsStatusFilter:
    def _records(self) -> list[ApplicationRecord]:
        return [
            _rec("a1", status=ApplicationStatus.TAILORED),
            _rec("a2", status=ApplicationStatus.TAILORED),
            _rec("a3", status=ApplicationStatus.APPLIED),
            _rec("a4", status=ApplicationStatus.REJECTED),
        ]

    def test_status_none_returns_all(self):
        records = self._records()
        assert filter_records(records, status_filter=None) == records

    def test_filter_tailored(self):
        result = filter_records(self._records(), status_filter=ApplicationStatus.TAILORED)
        assert len(result) == 2
        assert all(r.status == ApplicationStatus.TAILORED for r in result)

    def test_filter_applied(self):
        result = filter_records(self._records(), status_filter=ApplicationStatus.APPLIED)
        assert len(result) == 1
        assert result[0].application_id == "a3"

    def test_filter_with_no_matching_status(self):
        result = filter_records(
            self._records(), status_filter=ApplicationStatus.INTERVIEWING
        )
        assert result == []


# ---------------------------------------------------------------------------
# filter_records — combined query + status filter
# ---------------------------------------------------------------------------

class TestFilterRecordsCombined:
    def test_status_and_query_both_applied(self):
        records = [
            _rec("app-alpha", status=ApplicationStatus.TAILORED, notes="python role"),
            _rec("app-beta",  status=ApplicationStatus.TAILORED, notes="java role"),
            _rec("app-gamma", status=ApplicationStatus.APPLIED,  notes="python role"),
        ]
        result = filter_records(
            records,
            query="python",
            status_filter=ApplicationStatus.TAILORED,
        )
        assert len(result) == 1
        assert result[0].application_id == "app-alpha"

    def test_query_matches_but_status_filter_excludes(self):
        records = [_rec("a1", status=ApplicationStatus.TAILORED, notes="python")]
        result = filter_records(
            records,
            query="python",
            status_filter=ApplicationStatus.APPLIED,
        )
        assert result == []


# ---------------------------------------------------------------------------
# sort_records — SORT_NEWEST (default)
# ---------------------------------------------------------------------------

class TestSortRecordsNewest:
    def test_newest_is_default(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 3, 1, tzinfo=_UTC)
        records = [
            _rec("old", created_at=t1),
            _rec("new", created_at=t2),
        ]
        result = sort_records(records)
        assert result[0].application_id == "new"

    def test_newest_explicit_key(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 3, 1, tzinfo=_UTC)
        records = [
            _rec("old", created_at=t1),
            _rec("new", created_at=t2),
        ]
        result = sort_records(records, sort_key=SORT_NEWEST)
        assert result[0].application_id == "new"

    def test_unknown_sort_key_falls_back_to_newest(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 3, 1, tzinfo=_UTC)
        records = [
            _rec("old", created_at=t1),
            _rec("new", created_at=t2),
        ]
        result = sort_records(records, sort_key="not_a_real_key")
        assert result[0].application_id == "new"


# ---------------------------------------------------------------------------
# sort_records — SORT_OLDEST
# ---------------------------------------------------------------------------

class TestSortRecordsOldest:
    def test_oldest_first(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 3, 1, tzinfo=_UTC)
        records = [
            _rec("new", created_at=t2),
            _rec("old", created_at=t1),
        ]
        result = sort_records(records, sort_key=SORT_OLDEST)
        assert result[0].application_id == "old"


# ---------------------------------------------------------------------------
# sort_records — SORT_RECENTLY_UPDATED
# ---------------------------------------------------------------------------

class TestSortRecordsRecentlyUpdated:
    def test_most_recently_updated_first(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 6, 1, tzinfo=_UTC)
        records = [
            _rec("stale",   updated_at=t1),
            _rec("fresher", updated_at=t2),
        ]
        result = sort_records(records, sort_key=SORT_RECENTLY_UPDATED)
        assert result[0].application_id == "fresher"


# ---------------------------------------------------------------------------
# sort_records — SORT_APPLIED_AT (contract: newest first, None last)
# ---------------------------------------------------------------------------

class TestSortRecordsAppliedAt:
    def test_empty_input_returns_empty(self):
        assert sort_records([], sort_key=SORT_APPLIED_AT) == []

    def test_all_without_applied_at_unchanged_order(self):
        records = [
            _rec("a1", status=ApplicationStatus.TAILORED),
            _rec("a2", status=ApplicationStatus.TAILORED),
        ]
        result = sort_records(records, sort_key=SORT_APPLIED_AT)
        assert len(result) == 2
        # All have no applied_at — they should all come out, order preserved.
        ids = [r.application_id for r in result]
        assert set(ids) == {"a1", "a2"}

    def test_with_applied_at_before_without(self):
        early = datetime(2026, 1, 10, tzinfo=_UTC)
        records = [
            _rec("no_date",   status=ApplicationStatus.TAILORED),
            _rec("has_date",  status=ApplicationStatus.APPLIED, applied_at=early),
        ]
        result = sort_records(records, sort_key=SORT_APPLIED_AT)
        assert result[0].application_id == "has_date"
        assert result[1].application_id == "no_date"

    def test_newer_applied_at_comes_first(self):
        older = datetime(2026, 1, 1, tzinfo=_UTC)
        newer = datetime(2026, 6, 1, tzinfo=_UTC)
        records = [
            _rec("old_applied", status=ApplicationStatus.APPLIED, applied_at=older),
            _rec("new_applied", status=ApplicationStatus.APPLIED, applied_at=newer),
        ]
        result = sort_records(records, sort_key=SORT_APPLIED_AT)
        assert result[0].application_id == "new_applied"
        assert result[1].application_id == "old_applied"

    def test_mixed_applied_and_not_applied(self):
        d1 = datetime(2026, 1, 1, tzinfo=_UTC)
        d2 = datetime(2026, 6, 1, tzinfo=_UTC)
        records = [
            _rec("no_date_a", status=ApplicationStatus.TAILORED),
            _rec("old_date",  status=ApplicationStatus.APPLIED, applied_at=d1),
            _rec("no_date_b", status=ApplicationStatus.TAILORED),
            _rec("new_date",  status=ApplicationStatus.APPLIED, applied_at=d2),
        ]
        result = sort_records(records, sort_key=SORT_APPLIED_AT)
        ids = [r.application_id for r in result]
        # First two: dated records, newest first.
        assert ids[0] == "new_date"
        assert ids[1] == "old_date"
        # Last two: undated records (order among them is not specified).
        assert set(ids[2:]) == {"no_date_a", "no_date_b"}

    def test_none_applied_at_records_are_last(self):
        applied_at = datetime(2026, 3, 15, tzinfo=_UTC)
        records = [
            _rec("no_date", status=ApplicationStatus.TAILORED),
            _rec("dated",   status=ApplicationStatus.APPLIED, applied_at=applied_at),
        ]
        result = sort_records(records, sort_key=SORT_APPLIED_AT)
        assert result[-1].application_id == "no_date"


# ---------------------------------------------------------------------------
# sort_records — SORT_STATUS
# ---------------------------------------------------------------------------

class TestSortRecordsStatus:
    def test_sorted_alphabetically_by_status_value(self):
        records = [
            _rec("r_withdrawn",    status=ApplicationStatus.WITHDRAWN),
            _rec("r_applied",      status=ApplicationStatus.APPLIED),
            _rec("r_interviewing", status=ApplicationStatus.INTERVIEWING),
        ]
        result = sort_records(records, sort_key=SORT_STATUS)
        values = [r.status.value for r in result]
        assert values == sorted(values)


# ---------------------------------------------------------------------------
# apply_tracker_view — composed helper
# ---------------------------------------------------------------------------

class TestApplyTrackerView:
    def _records(self) -> list[ApplicationRecord]:
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 6, 1, tzinfo=_UTC)
        return [
            _rec("a1", status=ApplicationStatus.TAILORED, notes="python", created_at=t1),
            _rec("a2", status=ApplicationStatus.APPLIED,  notes="java",   created_at=t2),
            _rec("a3", status=ApplicationStatus.TAILORED, notes="python", created_at=t2),
        ]

    def test_empty_input_returns_empty(self):
        assert apply_tracker_view([]) == []

    def test_no_filters_returns_all_sorted_newest(self):
        records = self._records()
        result = apply_tracker_view(records)
        # newest created_at first: a2 and a3 share t2, a1 has t1
        assert result[-1].application_id == "a1"

    def test_query_and_status_filter_combined(self):
        records = self._records()
        result = apply_tracker_view(
            records,
            query="python",
            status_filter=ApplicationStatus.TAILORED,
        )
        # a1 and a3 are TAILORED + python; a2 is APPLIED
        assert len(result) == 2
        assert all(r.status == ApplicationStatus.TAILORED for r in result)

    def test_sort_key_applied_after_filter(self):
        t1 = datetime(2026, 1, 1, tzinfo=_UTC)
        t2 = datetime(2026, 6, 1, tzinfo=_UTC)
        records = [
            _rec("old_tailored", status=ApplicationStatus.TAILORED, created_at=t1),
            _rec("new_tailored", status=ApplicationStatus.TAILORED, created_at=t2),
            _rec("applied",      status=ApplicationStatus.APPLIED),
        ]
        result = apply_tracker_view(
            records,
            status_filter=ApplicationStatus.TAILORED,
            sort_key=SORT_OLDEST,
        )
        assert len(result) == 2
        assert result[0].application_id == "old_tailored"

    def test_filter_that_matches_nothing_returns_empty(self):
        records = self._records()
        result = apply_tracker_view(records, query="zzz_no_match")
        assert result == []


# ---------------------------------------------------------------------------
# TrackerService.update_notes
# ---------------------------------------------------------------------------

class TestTrackerServiceUpdateNotes:
    """Narrow contract tests for TrackerService.update_notes."""

    def _make_tracker(self, tmp_path):
        from app.reporting.tracker import TrackerService
        from app.storage.file_store import FileStore

        store = FileStore(tmp_path)
        return TrackerService(store)

    def _save_record(self, tracker, application_id="app1"):
        record = ApplicationRecord(
            application_id=application_id,
            job_id="job1",
            candidate_id="cand1",
            status=ApplicationStatus.TAILORED,
        )
        return tracker.save_application(record)

    def test_update_notes_returns_application_record(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        self._save_record(tracker)
        result = tracker.update_notes("app1", "call back Tuesday")
        from app.schemas.application import ApplicationRecord
        assert isinstance(result, ApplicationRecord)

    def test_update_notes_persists_new_notes(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        self._save_record(tracker)
        tracker.update_notes("app1", "follow up sent")
        reloaded = tracker.get_application("app1")
        assert reloaded.notes == "follow up sent"

    def test_update_notes_sets_updated_at(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        original = self._save_record(tracker)
        updated = tracker.update_notes("app1", "new note")
        assert updated.updated_at >= original.updated_at

    def test_update_notes_preserves_status(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        self._save_record(tracker)
        updated = tracker.update_notes("app1", "some note")
        assert updated.status == ApplicationStatus.TAILORED

    def test_update_notes_can_clear_notes(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        self._save_record(tracker)
        tracker.update_notes("app1", "initial note")
        tracker.update_notes("app1", "")
        reloaded = tracker.get_application("app1")
        assert reloaded.notes == ""

    def test_update_notes_raises_for_missing_id(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            tracker.update_notes("nonexistent", "some note")

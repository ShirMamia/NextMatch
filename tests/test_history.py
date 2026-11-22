"""
Tests for Slice 12 — HistoryService and audit event factory helpers.

Covers:
  - append_event persists an event retrievable by list_events_for_application.
  - list_events_for_application returns events in ascending created_at order.
  - list_events_for_application excludes events for other applications.
  - list_events_for_application returns empty list when no events exist.
  - Multiple events for the same application are all returned.
  - Each factory helper builds the correct concrete event type.
  - Factory helpers produce events with correct payload fields.
  - Factory helpers generate unique event_ids per call.
  - TrackerService.update_status emits STATUS_UPDATED event on success.
  - TrackerService.update_status still returns updated record when history append fails.
  - TrackerService.update_notes emits NOTES_UPDATED event on success.
  - TrackerService.update_notes still returns updated record when history append fails.
  - TrackerService.update_notes with unchanged notes emits no event (no-op guard).
  - No exception leaks from history append failure after successful primary persistence.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.reporting.history import (
    HistoryService,
    make_application_created_event,
    make_notes_updated_event,
    make_status_updated_event,
)
from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.schemas.application_event import (
    ApplicationCreatedEvent,
    NotesUpdatedEvent,
    StatusUpdatedEvent,
)
from app.storage.file_store import FileStore
from app.utils.ids import generate_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(tmp_path) -> HistoryService:
    return HistoryService(FileStore(tmp_path))


def _make_tracker_with_history(tmp_path) -> tuple[TrackerService, HistoryService]:
    store = FileStore(tmp_path)
    history = HistoryService(store)
    tracker = TrackerService(store, history=history)
    return tracker, history


def _tailored_record(application_id: str | None = None) -> ApplicationRecord:
    return ApplicationRecord(
        application_id=application_id or generate_id(),
        job_id="job-1",
        candidate_id="cand-1",
        resume_id="resume-1",
        status=ApplicationStatus.TAILORED,
    )


# ---------------------------------------------------------------------------
# HistoryService — basic persistence
# ---------------------------------------------------------------------------

class TestHistoryServicePersistence:

    def test_append_and_retrieve_single_event(self, tmp_path):
        history = _make_history(tmp_path)
        event = make_application_created_event(
            application_id="app1",
            initial_status=ApplicationStatus.TAILORED,
            job_id="job1",
            candidate_id="cand1",
        )
        history.append_event(event)
        events = history.list_events_for_application("app1")
        assert len(events) == 1
        assert events[0].event_id == event.event_id

    def test_list_events_empty_when_none_appended(self, tmp_path):
        history = _make_history(tmp_path)
        assert history.list_events_for_application("app1") == []

    def test_list_events_excludes_other_applications(self, tmp_path):
        history = _make_history(tmp_path)
        e1 = make_application_created_event("app1", ApplicationStatus.TAILORED, "j1", "c1")
        e2 = make_application_created_event("app2", ApplicationStatus.TAILORED, "j2", "c2")
        history.append_event(e1)
        history.append_event(e2)
        assert len(history.list_events_for_application("app1")) == 1
        assert len(history.list_events_for_application("app2")) == 1

    def test_multiple_events_for_same_application_all_returned(self, tmp_path):
        history = _make_history(tmp_path)
        e1 = make_application_created_event("app1", ApplicationStatus.TAILORED, "j1", "c1")
        e2 = make_status_updated_event("app1", ApplicationStatus.TAILORED, ApplicationStatus.APPLIED)
        e3 = make_notes_updated_event("app1", "", "some notes")
        history.append_event(e1)
        history.append_event(e2)
        history.append_event(e3)
        events = history.list_events_for_application("app1")
        assert len(events) == 3

    def test_list_events_returns_oldest_first(self, tmp_path):
        """Events must be returned sorted by created_at ascending (oldest first)."""
        history = _make_history(tmp_path)
        # Create events with guaranteed time ordering.
        e1 = make_application_created_event("app1", ApplicationStatus.TAILORED, "j1", "c1")
        time.sleep(0.01)
        e2 = make_status_updated_event("app1", ApplicationStatus.TAILORED, ApplicationStatus.APPLIED)
        history.append_event(e1)
        history.append_event(e2)
        events = history.list_events_for_application("app1")
        assert events[0].created_at <= events[1].created_at

    def test_restored_event_is_correct_concrete_type(self, tmp_path):
        history = _make_history(tmp_path)
        event = make_status_updated_event(
            "app1", ApplicationStatus.TAILORED, ApplicationStatus.APPLIED
        )
        history.append_event(event)
        events = history.list_events_for_application("app1")
        assert isinstance(events[0], StatusUpdatedEvent)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

class TestFactoryHelpers:

    def test_make_application_created_event_type(self):
        evt = make_application_created_event("app1", ApplicationStatus.TAILORED, "j1", "c1")
        assert isinstance(evt, ApplicationCreatedEvent)

    def test_make_application_created_event_payload(self):
        evt = make_application_created_event("app1", ApplicationStatus.TAILORED, "job-x", "cand-y")
        assert evt.application_id == "app1"
        assert evt.payload.initial_status == ApplicationStatus.TAILORED
        assert evt.payload.job_id == "job-x"
        assert evt.payload.candidate_id == "cand-y"

    def test_make_status_updated_event_type(self):
        evt = make_status_updated_event("app1", ApplicationStatus.TAILORED, ApplicationStatus.APPLIED)
        assert isinstance(evt, StatusUpdatedEvent)

    def test_make_status_updated_event_payload(self):
        evt = make_status_updated_event("app1", ApplicationStatus.TAILORED, ApplicationStatus.APPLIED)
        assert evt.application_id == "app1"
        assert evt.payload.old_status == ApplicationStatus.TAILORED
        assert evt.payload.new_status == ApplicationStatus.APPLIED

    def test_make_notes_updated_event_type(self):
        evt = make_notes_updated_event("app1", "old", "new")
        assert isinstance(evt, NotesUpdatedEvent)

    def test_make_notes_updated_event_payload(self):
        evt = make_notes_updated_event("app1", "before", "after")
        assert evt.application_id == "app1"
        assert evt.payload.old_notes == "before"
        assert evt.payload.new_notes == "after"

    def test_factory_generates_unique_event_ids(self):
        e1 = make_application_created_event("app1", ApplicationStatus.TAILORED, "j", "c")
        e2 = make_application_created_event("app1", ApplicationStatus.TAILORED, "j", "c")
        assert e1.event_id != e2.event_id

    def test_factory_event_has_utc_aware_created_at(self):
        from datetime import timezone
        evt = make_application_created_event("app1", ApplicationStatus.TAILORED, "j", "c")
        assert evt.created_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# TrackerService — STATUS_UPDATED event emission
# ---------------------------------------------------------------------------

class TestTrackerServiceStatusEvent:

    def test_update_status_emits_status_updated_event(self, tmp_path):
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        events = history.list_events_for_application(record.application_id)
        assert len(events) == 1
        assert isinstance(events[0], StatusUpdatedEvent)

    def test_update_status_event_payload_is_correct(self, tmp_path):
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        event = history.list_events_for_application(record.application_id)[0]
        assert isinstance(event, StatusUpdatedEvent)
        assert event.payload.old_status == ApplicationStatus.TAILORED
        assert event.payload.new_status == ApplicationStatus.APPLIED

    def test_update_status_no_event_on_invalid_transition(self, tmp_path):
        """Policy-blocked transitions must not emit events."""
        from datetime import datetime, timezone
        tracker, history = _make_tracker_with_history(tmp_path)
        record_rejected = ApplicationRecord(
            application_id="app-t",
            job_id="j1",
            candidate_id="c1",
            resume_id="r1",
            status=ApplicationStatus.REJECTED,
            applied_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        tracker.save_application(record_rejected)
        with pytest.raises(ValueError):
            tracker.update_status("app-t", ApplicationStatus.APPLIED)
        assert history.list_events_for_application("app-t") == []

    def test_update_status_returns_updated_record_when_history_append_fails(self, tmp_path):
        """Primary record update succeeds even if history emission raises."""
        store = FileStore(tmp_path)
        history = HistoryService(store)
        tracker = TrackerService(store, history=history)

        record = _tailored_record()
        tracker.save_application(record)

        # Patch append_event to raise after the primary save already happened.
        with patch.object(history, "append_event", side_effect=RuntimeError("storage failure")):
            updated = tracker.update_status(record.application_id, ApplicationStatus.APPLIED)

        # Primary update must have succeeded.
        assert updated.status == ApplicationStatus.APPLIED
        reloaded = tracker.get_application(record.application_id)
        assert reloaded.status == ApplicationStatus.APPLIED

    def test_update_status_history_failure_does_not_raise(self, tmp_path):
        """No exception must leak to the caller when history append fails."""
        store = FileStore(tmp_path)
        history = HistoryService(store)
        tracker = TrackerService(store, history=history)

        record = _tailored_record()
        tracker.save_application(record)

        with patch.object(history, "append_event", side_effect=RuntimeError("fail")):
            # Must not raise — only logs the failure.
            tracker.update_status(record.application_id, ApplicationStatus.APPLIED)


# ---------------------------------------------------------------------------
# TrackerService — NOTES_UPDATED event emission
# ---------------------------------------------------------------------------

class TestTrackerServiceNotesEvent:

    def test_update_notes_emits_notes_updated_event(self, tmp_path):
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        tracker.update_notes(record.application_id, "my notes")
        events = history.list_events_for_application(record.application_id)
        assert len(events) == 1
        assert isinstance(events[0], NotesUpdatedEvent)

    def test_update_notes_event_payload_is_correct(self, tmp_path):
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        tracker.update_notes(record.application_id, "my notes")
        event = history.list_events_for_application(record.application_id)[0]
        assert isinstance(event, NotesUpdatedEvent)
        assert event.payload.old_notes == ""
        assert event.payload.new_notes == "my notes"

    def test_update_notes_noop_emits_no_event(self, tmp_path):
        """Saving identical notes must not emit an event."""
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        # notes start as "" (empty); saving "" again is a no-op.
        tracker.update_notes(record.application_id, "")
        assert history.list_events_for_application(record.application_id) == []

    def test_update_notes_noop_returns_existing_record(self, tmp_path):
        """No-op notes update must return the current record unchanged."""
        tracker, history = _make_tracker_with_history(tmp_path)
        record = _tailored_record()
        tracker.save_application(record)
        result = tracker.update_notes(record.application_id, "")
        assert result.application_id == record.application_id
        assert result.notes in (None, "")

    def test_update_notes_returns_updated_record_when_history_append_fails(self, tmp_path):
        """Primary record update succeeds even if history emission raises."""
        store = FileStore(tmp_path)
        history = HistoryService(store)
        tracker = TrackerService(store, history=history)

        record = _tailored_record()
        tracker.save_application(record)

        with patch.object(history, "append_event", side_effect=RuntimeError("storage failure")):
            updated = tracker.update_notes(record.application_id, "notes content")

        assert updated.notes == "notes content"
        reloaded = tracker.get_application(record.application_id)
        assert reloaded.notes == "notes content"

    def test_update_notes_history_failure_does_not_raise(self, tmp_path):
        """No exception must leak to the caller when history append fails."""
        store = FileStore(tmp_path)
        history = HistoryService(store)
        tracker = TrackerService(store, history=history)

        record = _tailored_record()
        tracker.save_application(record)

        with patch.object(history, "append_event", side_effect=RuntimeError("fail")):
            # Must not raise — only logs the failure.
            tracker.update_notes(record.application_id, "safe notes")

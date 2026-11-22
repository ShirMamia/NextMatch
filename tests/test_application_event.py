"""
Tests for Slice 12 — application_event schema correctness.

Covers:
  - Each event type validates with the correct payload model.
  - Invalid payload type for a given event type fails validation.
  - Missing required payload fields fail validation.
  - Extra/irrelevant payload fields fail validation (extra="forbid").
  - Event instances are immutable after construction (frozen=True).
  - Payload instances are immutable after construction.
  - Serialization is clean and deterministic (round-trip via TypeAdapter).
  - ApplicationEventAdapter dispatches to the correct concrete class.
  - Default field generation: event_id is non-empty, created_at is UTC-aware.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.application import ApplicationStatus
from app.schemas.application_event import (
    ApplicationCreatedEvent,
    ApplicationCreatedPayload,
    ApplicationEvent,
    ApplicationEventAdapter,
    ApplicationEventType,
    NotesUpdatedEvent,
    NotesUpdatedPayload,
    StatusUpdatedEvent,
    StatusUpdatedPayload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _created_event(**overrides) -> ApplicationCreatedEvent:
    kwargs = dict(
        application_id="app1",
        payload=ApplicationCreatedPayload(
            initial_status=ApplicationStatus.TAILORED,
            job_id="job1",
            candidate_id="cand1",
        ),
    )
    kwargs.update(overrides)
    return ApplicationCreatedEvent(**kwargs)


def _status_event(**overrides) -> StatusUpdatedEvent:
    kwargs = dict(
        application_id="app1",
        payload=StatusUpdatedPayload(
            old_status=ApplicationStatus.TAILORED,
            new_status=ApplicationStatus.APPLIED,
        ),
    )
    kwargs.update(overrides)
    return StatusUpdatedEvent(**kwargs)


def _notes_event(**overrides) -> NotesUpdatedEvent:
    kwargs = dict(
        application_id="app1",
        payload=NotesUpdatedPayload(old_notes="", new_notes="some notes"),
    )
    kwargs.update(overrides)
    return NotesUpdatedEvent(**kwargs)


# ---------------------------------------------------------------------------
# ApplicationCreatedEvent
# ---------------------------------------------------------------------------

class TestApplicationCreatedEvent:

    def test_valid_construction(self):
        evt = _created_event()
        assert evt.event_type == ApplicationEventType.APPLICATION_CREATED
        assert evt.application_id == "app1"
        assert evt.payload.initial_status == ApplicationStatus.TAILORED

    def test_event_id_generated(self):
        evt = _created_event()
        assert isinstance(evt.event_id, str)
        assert len(evt.event_id) > 0

    def test_created_at_is_utc_aware(self):
        from datetime import timezone
        evt = _created_event()
        assert evt.created_at.tzinfo is not None
        assert evt.created_at.tzinfo == timezone.utc

    def test_two_events_have_distinct_event_ids(self):
        e1 = _created_event()
        e2 = _created_event()
        assert e1.event_id != e2.event_id

    def test_immutable_event(self):
        evt = _created_event()
        with pytest.raises(ValidationError):
            evt.application_id = "other"

    def test_immutable_payload(self):
        payload = ApplicationCreatedPayload(
            initial_status=ApplicationStatus.TAILORED,
            job_id="j1",
            candidate_id="c1",
        )
        with pytest.raises(ValidationError):
            payload.job_id = "changed"

    def test_extra_field_on_event_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreatedEvent(
                application_id="app1",
                payload=ApplicationCreatedPayload(
                    initial_status=ApplicationStatus.TAILORED,
                    job_id="j1",
                    candidate_id="c1",
                ),
                unexpected_field="boom",
            )

    def test_extra_field_on_payload_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreatedPayload(
                initial_status=ApplicationStatus.TAILORED,
                job_id="j1",
                candidate_id="c1",
                unexpected="boom",
            )

    def test_missing_job_id_in_payload_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreatedPayload(
                initial_status=ApplicationStatus.TAILORED,
                candidate_id="c1",
            )

    def test_missing_candidate_id_in_payload_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreatedPayload(
                initial_status=ApplicationStatus.TAILORED,
                job_id="j1",
            )

    def test_invalid_initial_status_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreatedPayload(
                initial_status="not_a_status",
                job_id="j1",
                candidate_id="c1",
            )


# ---------------------------------------------------------------------------
# StatusUpdatedEvent
# ---------------------------------------------------------------------------

class TestStatusUpdatedEvent:

    def test_valid_construction(self):
        evt = _status_event()
        assert evt.event_type == ApplicationEventType.STATUS_UPDATED
        assert evt.payload.old_status == ApplicationStatus.TAILORED
        assert evt.payload.new_status == ApplicationStatus.APPLIED

    def test_immutable_event(self):
        evt = _status_event()
        with pytest.raises(ValidationError):
            evt.application_id = "changed"

    def test_immutable_payload(self):
        payload = StatusUpdatedPayload(
            old_status=ApplicationStatus.TAILORED,
            new_status=ApplicationStatus.APPLIED,
        )
        with pytest.raises(ValidationError):
            payload.new_status = ApplicationStatus.REJECTED

    def test_extra_field_on_payload_rejected(self):
        with pytest.raises(ValidationError):
            StatusUpdatedPayload(
                old_status=ApplicationStatus.TAILORED,
                new_status=ApplicationStatus.APPLIED,
                extra_junk="boom",
            )

    def test_missing_old_status_rejected(self):
        with pytest.raises(ValidationError):
            StatusUpdatedPayload(new_status=ApplicationStatus.APPLIED)

    def test_missing_new_status_rejected(self):
        with pytest.raises(ValidationError):
            StatusUpdatedPayload(old_status=ApplicationStatus.TAILORED)

    def test_invalid_old_status_rejected(self):
        with pytest.raises(ValidationError):
            StatusUpdatedPayload(old_status="bad", new_status=ApplicationStatus.APPLIED)


# ---------------------------------------------------------------------------
# NotesUpdatedEvent
# ---------------------------------------------------------------------------

class TestNotesUpdatedEvent:

    def test_valid_construction(self):
        evt = _notes_event()
        assert evt.event_type == ApplicationEventType.NOTES_UPDATED
        assert evt.payload.old_notes == ""
        assert evt.payload.new_notes == "some notes"

    def test_empty_notes_allowed(self):
        evt = _notes_event()
        assert isinstance(evt.payload.old_notes, str)
        assert isinstance(evt.payload.new_notes, str)

    def test_immutable_event(self):
        evt = _notes_event()
        with pytest.raises(ValidationError):
            evt.application_id = "changed"

    def test_immutable_payload(self):
        payload = NotesUpdatedPayload(old_notes="a", new_notes="b")
        with pytest.raises(ValidationError):
            payload.new_notes = "c"

    def test_extra_field_on_payload_rejected(self):
        with pytest.raises(ValidationError):
            NotesUpdatedPayload(old_notes="a", new_notes="b", extra="boom")

    def test_missing_old_notes_rejected(self):
        with pytest.raises(ValidationError):
            NotesUpdatedPayload(new_notes="b")

    def test_missing_new_notes_rejected(self):
        with pytest.raises(ValidationError):
            NotesUpdatedPayload(old_notes="a")


# ---------------------------------------------------------------------------
# Discriminated union — ApplicationEventAdapter round-trips
# ---------------------------------------------------------------------------

class TestApplicationEventAdapter:

    def test_adapter_round_trips_created_event(self):
        evt = _created_event()
        raw = evt.model_dump(mode="json")
        restored = ApplicationEventAdapter.validate_python(raw)
        assert isinstance(restored, ApplicationCreatedEvent)
        assert restored.event_id == evt.event_id
        assert restored.payload.job_id == evt.payload.job_id

    def test_adapter_round_trips_status_event(self):
        evt = _status_event()
        raw = evt.model_dump(mode="json")
        restored = ApplicationEventAdapter.validate_python(raw)
        assert isinstance(restored, StatusUpdatedEvent)
        assert restored.payload.old_status == ApplicationStatus.TAILORED
        assert restored.payload.new_status == ApplicationStatus.APPLIED

    def test_adapter_round_trips_notes_event(self):
        evt = _notes_event()
        raw = evt.model_dump(mode="json")
        restored = ApplicationEventAdapter.validate_python(raw)
        assert isinstance(restored, NotesUpdatedEvent)
        assert restored.payload.new_notes == "some notes"

    def test_adapter_rejects_unknown_event_type(self):
        with pytest.raises(ValidationError):
            ApplicationEventAdapter.validate_python({
                "event_type": "unknown_type",
                "event_id": "e1",
                "application_id": "app1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "payload": {},
            })

    def test_adapter_rejects_missing_event_type(self):
        with pytest.raises(ValidationError):
            ApplicationEventAdapter.validate_python({
                "event_id": "e1",
                "application_id": "app1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "payload": {},
            })

    def test_adapter_selects_correct_class_for_each_type(self):
        """The discriminator routes each event_type to the right concrete class."""
        events = [_created_event(), _status_event(), _notes_event()]
        expected_types = [ApplicationCreatedEvent, StatusUpdatedEvent, NotesUpdatedEvent]
        for evt, expected in zip(events, expected_types):
            raw = evt.model_dump(mode="json")
            restored = ApplicationEventAdapter.validate_python(raw)
            assert type(restored) is expected

    def test_serialization_contains_event_type_string(self):
        """model_dump(mode='json') must produce the string discriminator value."""
        evt = _created_event()
        raw = evt.model_dump(mode="json")
        assert raw["event_type"] == "application_created"

    def test_wrong_payload_shape_for_event_type_rejected(self):
        """Providing StatusUpdated payload fields in an APPLICATION_CREATED dict is rejected."""
        with pytest.raises(ValidationError):
            ApplicationEventAdapter.validate_python({
                "event_type": "application_created",
                "event_id": "e1",
                "application_id": "app1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "payload": {
                    # These are StatusUpdatedPayload fields — wrong for APPLICATION_CREATED
                    "old_status": "tailored",
                    "new_status": "applied",
                },
            })

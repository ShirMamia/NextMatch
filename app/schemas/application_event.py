"""
Application event schema — Slice 12.

Provides a strongly typed, immutable, append-only audit schema for application
lifecycle events.

Design:
  - One payload model per event type (frozen=True, extra="forbid").
  - One event class per event type with a Literal discriminator on event_type
    and an explicitly typed payload field.
  - All models are frozen — mutation after construction raises ValidationError.
  - ApplicationEvent is a discriminated union type alias; Pydantic selects the
    correct concrete class via the event_type discriminator during validation.
  - ApplicationEventAdapter (TypeAdapter) is the correct tool for deserializing
    events loaded from the repository (plain dicts → concrete event instances).

Supported event types:
  application_created — emitted by approve_and_save() when a new ApplicationRecord
                        is created via the approval pipeline.
  status_updated      — emitted by TrackerService.update_status() on success.
  notes_updated       — emitted by TrackerService.update_notes() on success.

Events are never mutated after being written to the repository.
The event_id field is unique per event; saves to the repository are therefore
effectively append-only even though the underlying store supports key overwrite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas.application import ApplicationStatus
from app.utils.ids import generate_id


# ---------------------------------------------------------------------------
# Event type enum
# ---------------------------------------------------------------------------

class ApplicationEventType(str, Enum):
    APPLICATION_CREATED = "application_created"
    STATUS_UPDATED = "status_updated"
    NOTES_UPDATED = "notes_updated"


# ---------------------------------------------------------------------------
# Payload models — one per event type, strictly validated and frozen
# ---------------------------------------------------------------------------

class ApplicationCreatedPayload(BaseModel):
    """Payload for APPLICATION_CREATED events.

    Fields:
        initial_status: the ApplicationStatus when the record was first created.
        job_id:         the job this application targets.
        candidate_id:   the candidate who owns this application.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    initial_status: ApplicationStatus
    job_id: str
    candidate_id: str


class StatusUpdatedPayload(BaseModel):
    """Payload for STATUS_UPDATED events.

    Fields:
        old_status: the ApplicationStatus before the transition.
        new_status: the ApplicationStatus after the transition.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    old_status: ApplicationStatus
    new_status: ApplicationStatus


class NotesUpdatedPayload(BaseModel):
    """Payload for NOTES_UPDATED events.

    Fields:
        old_notes: the notes value before the update (may be empty string).
        new_notes: the notes value after the update (may be empty string).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    old_notes: str
    new_notes: str


# ---------------------------------------------------------------------------
# Shared event base
# ---------------------------------------------------------------------------

class _EventBase(BaseModel):
    """Common fields shared by all application event types."""

    model_config = {"frozen": True, "extra": "forbid"}

    event_id: str = Field(default_factory=generate_id)
    application_id: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Concrete event classes — one per event type
# ---------------------------------------------------------------------------

class ApplicationCreatedEvent(_EventBase):
    """Emitted when a new ApplicationRecord is created via the approval pipeline."""

    event_type: Literal[ApplicationEventType.APPLICATION_CREATED] = (
        ApplicationEventType.APPLICATION_CREATED
    )
    payload: ApplicationCreatedPayload


class StatusUpdatedEvent(_EventBase):
    """Emitted when TrackerService.update_status() succeeds."""

    event_type: Literal[ApplicationEventType.STATUS_UPDATED] = (
        ApplicationEventType.STATUS_UPDATED
    )
    payload: StatusUpdatedPayload


class NotesUpdatedEvent(_EventBase):
    """Emitted when TrackerService.update_notes() succeeds."""

    event_type: Literal[ApplicationEventType.NOTES_UPDATED] = (
        ApplicationEventType.NOTES_UPDATED
    )
    payload: NotesUpdatedPayload


# ---------------------------------------------------------------------------
# Discriminated union type alias + TypeAdapter
# ---------------------------------------------------------------------------

# ApplicationEvent is the canonical type for any event in the audit trail.
# Pydantic uses the event_type discriminator to select the concrete class.
ApplicationEvent = Annotated[
    ApplicationCreatedEvent | StatusUpdatedEvent | NotesUpdatedEvent,
    Field(discriminator="event_type"),
]

# Use ApplicationEventAdapter to validate/deserialize events loaded from the
# repository (plain dicts → concrete event instances).
ApplicationEventAdapter: TypeAdapter[ApplicationEvent] = TypeAdapter(ApplicationEvent)

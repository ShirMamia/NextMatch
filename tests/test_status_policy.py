"""
Tests for Slice 11 — status transition policy and service-layer enforcement.

Covers:
  - allowed_target_statuses: returns correct targets for representative statuses
  - allowed_target_statuses: terminal statuses return empty list
  - allowed_target_statuses: all statuses covered (no KeyError)
  - allowed_target_statuses: results are in enum-definition order
  - is_valid_transition: valid transitions return True
  - is_valid_transition: invalid transitions return False
  - explain_invalid_transition: returns non-empty string
  - explain_invalid_transition: terminal-status message differs from general message
  - TrackerService.update_status: valid transition persists
  - TrackerService.update_status: invalid transition raises ValueError
  - TrackerService.update_status: no persistence occurs on invalid transition
  - TrackerService.update_status: applied_at behavior preserved on valid transition
"""
from __future__ import annotations

import pytest

from app.reporting.status_policy import (
    allowed_target_statuses,
    explain_invalid_transition,
    is_valid_transition,
)
from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.storage.file_store import FileStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path):
    return TrackerService(FileStore(tmp_path))


def _make_record(
    status: ApplicationStatus = ApplicationStatus.TAILORED,
    application_id: str = "app1",
    resume_id: str | None = None,
) -> ApplicationRecord:
    """Build a minimal valid ApplicationRecord for the given status."""
    from datetime import datetime, timezone

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

    applied_at = None
    if status in _requires_applied:
        applied_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    if resume_id is None and status in _requires_resume:
        resume_id = "resume_test"

    return ApplicationRecord(
        application_id=application_id,
        job_id="job1",
        candidate_id="cand1",
        status=status,
        resume_id=resume_id,
        applied_at=applied_at,
    )


# ---------------------------------------------------------------------------
# allowed_target_statuses
# ---------------------------------------------------------------------------

class TestAllowedTargetStatuses:

    def test_every_status_is_covered(self):
        """No status raises a KeyError — the policy table is complete."""
        for status in ApplicationStatus:
            result = allowed_target_statuses(status)
            assert isinstance(result, list)

    def test_discovered_allows_saved(self):
        result = allowed_target_statuses(ApplicationStatus.DISCOVERED)
        assert ApplicationStatus.SAVED in result

    def test_tailored_allows_approved_and_applied(self):
        result = allowed_target_statuses(ApplicationStatus.TAILORED)
        assert ApplicationStatus.APPROVED in result
        assert ApplicationStatus.APPLIED in result

    def test_approved_allows_applied_and_tailored(self):
        result = allowed_target_statuses(ApplicationStatus.APPROVED)
        assert ApplicationStatus.APPLIED in result
        assert ApplicationStatus.TAILORED in result

    def test_applied_allows_interviewing_rejected_withdrawn_tailored(self):
        result = allowed_target_statuses(ApplicationStatus.APPLIED)
        assert ApplicationStatus.INTERVIEWING in result
        assert ApplicationStatus.REJECTED in result
        assert ApplicationStatus.WITHDRAWN in result
        assert ApplicationStatus.TAILORED in result

    def test_interviewing_allows_offered_rejected_withdrawn_applied(self):
        result = allowed_target_statuses(ApplicationStatus.INTERVIEWING)
        assert ApplicationStatus.OFFERED in result
        assert ApplicationStatus.REJECTED in result
        assert ApplicationStatus.WITHDRAWN in result
        assert ApplicationStatus.APPLIED in result

    def test_offered_allows_withdrawn_only(self):
        result = allowed_target_statuses(ApplicationStatus.OFFERED)
        assert result == [ApplicationStatus.WITHDRAWN]

    def test_rejected_is_terminal(self):
        assert allowed_target_statuses(ApplicationStatus.REJECTED) == []

    def test_withdrawn_is_terminal(self):
        assert allowed_target_statuses(ApplicationStatus.WITHDRAWN) == []

    def test_results_in_enum_definition_order(self):
        """Returned list must follow ApplicationStatus enum-definition order."""
        enum_list = list(ApplicationStatus)
        for status in ApplicationStatus:
            result = allowed_target_statuses(status)
            positions = [enum_list.index(s) for s in result]
            assert positions == sorted(positions), (
                f"allowed_target_statuses({status.value}) is not in enum order: {result}"
            )

    def test_current_status_not_in_its_own_targets(self):
        """No status should be a valid target of itself."""
        for status in ApplicationStatus:
            assert status not in allowed_target_statuses(status)


# ---------------------------------------------------------------------------
# is_valid_transition
# ---------------------------------------------------------------------------

class TestIsValidTransition:

    # Valid transitions
    def test_discovered_to_saved(self):
        assert is_valid_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.SAVED)

    def test_saved_to_tailored(self):
        assert is_valid_transition(ApplicationStatus.SAVED, ApplicationStatus.TAILORED)

    def test_tailored_to_approved(self):
        assert is_valid_transition(ApplicationStatus.TAILORED, ApplicationStatus.APPROVED)

    def test_tailored_to_applied_direct(self):
        """Direct shortcut: TAILORED → APPLIED without APPROVED."""
        assert is_valid_transition(ApplicationStatus.TAILORED, ApplicationStatus.APPLIED)

    def test_approved_to_applied(self):
        assert is_valid_transition(ApplicationStatus.APPROVED, ApplicationStatus.APPLIED)

    def test_applied_to_interviewing(self):
        assert is_valid_transition(ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEWING)

    def test_applied_to_rejected(self):
        assert is_valid_transition(ApplicationStatus.APPLIED, ApplicationStatus.REJECTED)

    def test_applied_to_withdrawn(self):
        assert is_valid_transition(ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN)

    def test_applied_to_tailored_backward(self):
        """Documented correction move: APPLIED → TAILORED."""
        assert is_valid_transition(ApplicationStatus.APPLIED, ApplicationStatus.TAILORED)

    def test_interviewing_to_offered(self):
        assert is_valid_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFERED)

    def test_interviewing_to_rejected(self):
        assert is_valid_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.REJECTED)

    def test_interviewing_to_withdrawn(self):
        assert is_valid_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.WITHDRAWN)

    def test_interviewing_to_applied_backward(self):
        assert is_valid_transition(ApplicationStatus.INTERVIEWING, ApplicationStatus.APPLIED)

    def test_offered_to_withdrawn(self):
        assert is_valid_transition(ApplicationStatus.OFFERED, ApplicationStatus.WITHDRAWN)

    # Invalid transitions
    def test_rejected_to_applied_blocked(self):
        assert not is_valid_transition(ApplicationStatus.REJECTED, ApplicationStatus.APPLIED)

    def test_rejected_to_interviewing_blocked(self):
        assert not is_valid_transition(ApplicationStatus.REJECTED, ApplicationStatus.INTERVIEWING)

    def test_withdrawn_to_interviewing_blocked(self):
        assert not is_valid_transition(ApplicationStatus.WITHDRAWN, ApplicationStatus.INTERVIEWING)

    def test_withdrawn_to_applied_blocked(self):
        assert not is_valid_transition(ApplicationStatus.WITHDRAWN, ApplicationStatus.APPLIED)

    def test_discovered_to_offered_blocked(self):
        assert not is_valid_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.OFFERED)

    def test_saved_to_rejected_blocked(self):
        assert not is_valid_transition(ApplicationStatus.SAVED, ApplicationStatus.REJECTED)

    def test_tailored_to_interviewing_blocked(self):
        assert not is_valid_transition(ApplicationStatus.TAILORED, ApplicationStatus.INTERVIEWING)

    def test_offered_to_applied_blocked(self):
        assert not is_valid_transition(ApplicationStatus.OFFERED, ApplicationStatus.APPLIED)

    def test_offered_to_interviewing_blocked(self):
        assert not is_valid_transition(ApplicationStatus.OFFERED, ApplicationStatus.INTERVIEWING)


# ---------------------------------------------------------------------------
# explain_invalid_transition
# ---------------------------------------------------------------------------

class TestExplainInvalidTransition:

    def test_returns_non_empty_string(self):
        msg = explain_invalid_transition(
            ApplicationStatus.REJECTED, ApplicationStatus.APPLIED
        )
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_terminal_message_mentions_terminal(self):
        msg = explain_invalid_transition(
            ApplicationStatus.REJECTED, ApplicationStatus.APPLIED
        )
        assert "terminal" in msg.lower()

    def test_non_terminal_message_mentions_allowed_targets(self):
        msg = explain_invalid_transition(
            ApplicationStatus.TAILORED, ApplicationStatus.INTERVIEWING
        )
        # Should mention at least one of the valid targets from TAILORED.
        assert "approved" in msg or "applied" in msg

    def test_message_mentions_target_status(self):
        msg = explain_invalid_transition(
            ApplicationStatus.SAVED, ApplicationStatus.REJECTED
        )
        assert "rejected" in msg

    def test_message_mentions_source_status(self):
        msg = explain_invalid_transition(
            ApplicationStatus.SAVED, ApplicationStatus.REJECTED
        )
        assert "saved" in msg

    def test_withdrawn_terminal_message(self):
        msg = explain_invalid_transition(
            ApplicationStatus.WITHDRAWN, ApplicationStatus.INTERVIEWING
        )
        assert "terminal" in msg.lower()


# ---------------------------------------------------------------------------
# TrackerService.update_status — policy enforcement
# ---------------------------------------------------------------------------

class TestTrackerServicePolicyEnforcement:

    def test_valid_transition_persists(self, tmp_path):
        """TAILORED → APPLIED: valid and schema-compatible (resume_id provided)."""
        tracker = _make_tracker(tmp_path)
        # resume_id required because APPLIED requires it per schema.
        record = _make_record(status=ApplicationStatus.TAILORED, resume_id="resume_test")
        tracker.save_application(record)
        updated = tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        assert updated.status == ApplicationStatus.APPLIED

    def test_invalid_transition_raises_value_error(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = _make_record(status=ApplicationStatus.REJECTED, resume_id="r1")
        tracker.save_application(record)
        with pytest.raises(ValueError):
            tracker.update_status(record.application_id, ApplicationStatus.APPLIED)

    def test_invalid_transition_error_message_is_readable(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = _make_record(status=ApplicationStatus.WITHDRAWN, resume_id="r1")
        tracker.save_application(record)
        with pytest.raises(ValueError, match="terminal"):
            tracker.update_status(record.application_id, ApplicationStatus.INTERVIEWING)

    def test_no_persistence_on_invalid_transition(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = _make_record(status=ApplicationStatus.REJECTED, resume_id="r1")
        tracker.save_application(record)
        with pytest.raises(ValueError):
            tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        # Record must still be REJECTED — no partial write occurred.
        reloaded = tracker.get_application(record.application_id)
        assert reloaded.status == ApplicationStatus.REJECTED

    def test_applied_at_set_on_valid_transition_to_applied(self, tmp_path):
        """resume_id required by schema for APPLIED — provided explicitly."""
        tracker = _make_tracker(tmp_path)
        record = _make_record(status=ApplicationStatus.TAILORED, resume_id="resume_test")
        tracker.save_application(record)
        updated = tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        assert updated.applied_at is not None

    def test_applied_at_cleared_on_valid_backward_to_tailored(self, tmp_path):
        """APPLIED → TAILORED is a valid correction move; applied_at must be cleared.
        resume_id is required for APPLIED by schema, so we provide it on the source record."""
        tracker = _make_tracker(tmp_path)
        record = _make_record(status=ApplicationStatus.TAILORED, resume_id="resume_test")
        tracker.save_application(record)
        tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        reverted = tracker.update_status(record.application_id, ApplicationStatus.TAILORED)
        assert reverted.applied_at is None

    def test_terminal_to_any_raises_value_error(self, tmp_path):
        """Both terminal statuses (REJECTED, WITHDRAWN) must block all transitions."""
        for terminal in (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN):
            tracker = _make_tracker(tmp_path)
            record = _make_record(
                status=terminal, resume_id="r1", application_id="app_t"
            )
            tracker.save_application(record)
            for target in ApplicationStatus:
                if target == terminal:
                    continue
                with pytest.raises(ValueError):
                    tracker.update_status(record.application_id, target)

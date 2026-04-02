"""
Focused tests for Slice 8 — Application Tracker and Approval Pipeline.

Covers:
  1.  approve_and_save blocked when resume is None
  2.  approve_and_save blocked when resume_report is None
  3.  approve_and_save blocked when resume_report failed
  4.  approve_and_save blocked when resume_report has wrong artifact_id
  5.  approve_and_save blocked when cl present but cl_report is None
  6.  approve_and_save blocked when cl_report failed
  7.  approve_and_save blocked when cl_report has wrong artifact_id
  8.  approve_and_save succeeds with all conditions met
  9.  returns exact object from tracker.save_application
  10. ApplicationRecord initial status is TAILORED
  11. approved artifacts are persisted to repo
  12. gate failure does not write to repo or tracker
  13. tracker.list_applications returns saved records
  14. tracker.update_status persists the new status
  15. tracker.update_status sets applied_at for APPLIED
  16. tracker.update_status clears applied_at when reverting to TAILORED
  17. tracker.update_status raises ValueError for unknown application_id
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.orchestration.application_pipeline import ApprovalError, approve_and_save
from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.schemas.tailoring import CoverLetterDraft, EvidenceLink, GroundedText, TailoredBullet, TailoredResume
from app.schemas.validation import FlagSeverity, FlagType, ValidationFlag, ValidationReport
from app.storage.file_store import FileStore
from app.utils.ids import generate_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ev() -> EvidenceLink:
    return EvidenceLink(
        source_bullet="Worked on backend services",
        source_section="work_experience[0].bullets[0]",
        confidence=0.9,
    )


def _bullet() -> TailoredBullet:
    return TailoredBullet(
        original="Worked on backend services",
        tailored="Built and maintained scalable backend services",
        evidence=_ev(),
    )


def _resume(resume_id: str | None = None) -> TailoredResume:
    rid = resume_id or generate_id()
    return TailoredResume(
        resume_id=rid,
        candidate_id="cand-1",
        job_id="job-1",
        match_id="match-1",
        summary=GroundedText(text="Experienced engineer", evidence_links=[_ev()]),
        sections={"work_experience[0] — Acme — Engineer": [_bullet()]},
    )


def _cover_letter(draft_id: str | None = None) -> CoverLetterDraft:
    did = draft_id or generate_id()
    return CoverLetterDraft(
        draft_id=did,
        candidate_id="cand-1",
        job_id="job-1",
        match_id="match-1",
        body="Dear Hiring Manager...",
        evidence_links=[_ev()],
    )


def _passing_report(artifact_id: str) -> ValidationReport:
    return ValidationReport(artifact_id=artifact_id, flags=[])


def _failing_report(artifact_id: str) -> ValidationReport:
    return ValidationReport(
        artifact_id=artifact_id,
        flags=[
            ValidationFlag(
                flag_id=generate_id(),
                severity=FlagSeverity.CRITICAL,
                flag_type=FlagType.EMPTY_CONTENT,
                message="Empty content",
                location="body",
            )
        ],
    )


def _make_tracker(tmp_path: Path) -> TrackerService:
    store = FileStore(tmp_path)
    return TrackerService(store)


def _make_store(tmp_path: Path) -> FileStore:
    return FileStore(tmp_path)


# ---------------------------------------------------------------------------
# ApprovalError gate tests
# ---------------------------------------------------------------------------

class TestApprovalGate:

    def test_blocked_when_resume_is_none(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="tailored resume is required"):
            approve_and_save(None, None, None, None, tracker, store)

    def test_blocked_when_resume_report_is_none(self, tmp_path):
        resume = _resume()
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="Resume validation is required"):
            approve_and_save(resume, None, None, None, tracker, store)

    def test_blocked_when_resume_report_failed(self, tmp_path):
        resume = _resume()
        report = _failing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="Resume validation failed"):
            approve_and_save(resume, None, report, None, tracker, store)

    def test_blocked_when_resume_report_has_wrong_artifact_id(self, tmp_path):
        resume = _resume()
        wrong_report = _passing_report("wrong-id")
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="does not match the current resume draft"):
            approve_and_save(resume, None, wrong_report, None, tracker, store)

    def test_blocked_when_cl_present_but_cl_report_is_none(self, tmp_path):
        resume = _resume()
        cl = _cover_letter()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="Cover letter validation is required"):
            approve_and_save(resume, cl, resume_report, None, tracker, store)

    def test_blocked_when_cl_report_failed(self, tmp_path):
        resume = _resume()
        cl = _cover_letter()
        resume_report = _passing_report(resume.resume_id)
        cl_report = _failing_report(cl.draft_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="Cover letter validation failed"):
            approve_and_save(resume, cl, resume_report, cl_report, tracker, store)

    def test_blocked_when_cl_report_has_wrong_artifact_id(self, tmp_path):
        resume = _resume()
        cl = _cover_letter()
        resume_report = _passing_report(resume.resume_id)
        wrong_cl_report = _passing_report("wrong-cl-id")
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        with pytest.raises(ApprovalError, match="does not match the current cover letter draft"):
            approve_and_save(resume, cl, resume_report, wrong_cl_report, tracker, store)

    def test_gate_failure_does_not_write_to_repo_or_tracker(self, tmp_path):
        """When the gate fails, no artifacts and no application record are persisted."""
        mock_tracker = MagicMock(spec=TrackerService)
        mock_repo = MagicMock()
        resume = _resume()
        with pytest.raises(ApprovalError):
            approve_and_save(resume, None, None, None, mock_tracker, mock_repo)
        mock_repo.save.assert_not_called()
        mock_tracker.save_application.assert_not_called()


# ---------------------------------------------------------------------------
# Successful approval tests
# ---------------------------------------------------------------------------

class TestApproveAndSaveSuccess:

    def test_returns_application_record(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        result = approve_and_save(resume, None, resume_report, None, tracker, store)
        assert isinstance(result, ApplicationRecord)

    def test_returns_exact_object_from_tracker(self, tmp_path):
        """approve_and_save must return the ApplicationRecord from tracker.save_application."""
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        real_store = _make_store(tmp_path)
        sentinel = object()
        mock_tracker = MagicMock(spec=TrackerService)
        mock_tracker.save_application.return_value = sentinel
        result = approve_and_save(resume, None, resume_report, None, mock_tracker, real_store)
        assert result is sentinel

    def test_initial_status_is_tailored(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        record = approve_and_save(resume, None, resume_report, None, tracker, store)
        assert record.status == ApplicationStatus.TAILORED

    def test_record_has_correct_ids(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        record = approve_and_save(resume, None, resume_report, None, tracker, store)
        assert record.job_id == resume.job_id
        assert record.candidate_id == resume.candidate_id
        assert record.resume_id == resume.resume_id

    def test_approved_resume_persisted_to_repo(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        approve_and_save(resume, None, resume_report, None, tracker, store)
        raw = store.load("tailored_resumes", resume.resume_id)
        assert raw is not None
        assert raw["approved"] is True
        assert raw["approved_at"] is not None

    def test_cover_letter_persisted_when_present(self, tmp_path):
        resume = _resume()
        cl = _cover_letter()
        resume_report = _passing_report(resume.resume_id)
        cl_report = _passing_report(cl.draft_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        approve_and_save(resume, cl, resume_report, cl_report, tracker, store)
        raw = store.load("cover_letters", cl.draft_id)
        assert raw is not None
        assert raw["draft_id"] == cl.draft_id

    def test_no_cover_letter_not_persisted_when_absent(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        approve_and_save(resume, None, resume_report, None, tracker, store)
        assert store.load_all("cover_letters") == []

    def test_application_record_persisted_to_tracker(self, tmp_path):
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        record = approve_and_save(resume, None, resume_report, None, tracker, store)
        loaded = tracker.get_application(record.application_id)
        assert loaded is not None
        assert loaded.application_id == record.application_id

    def test_succeeds_without_cover_letter(self, tmp_path):
        """Cover letter is optional — approval succeeds with resume only."""
        resume = _resume()
        resume_report = _passing_report(resume.resume_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        record = approve_and_save(resume, None, resume_report, None, tracker, store)
        assert record.status == ApplicationStatus.TAILORED

    def test_succeeds_with_cover_letter(self, tmp_path):
        resume = _resume()
        cl = _cover_letter()
        resume_report = _passing_report(resume.resume_id)
        cl_report = _passing_report(cl.draft_id)
        tracker = _make_tracker(tmp_path)
        store = _make_store(tmp_path)
        record = approve_and_save(resume, cl, resume_report, cl_report, tracker, store)
        assert record.status == ApplicationStatus.TAILORED


# ---------------------------------------------------------------------------
# TrackerService CRUD tests
# ---------------------------------------------------------------------------

class TestTrackerService:

    def _record(self, **kwargs) -> ApplicationRecord:
        defaults = dict(
            application_id=generate_id(),
            job_id="job-1",
            candidate_id="cand-1",
            resume_id="resume-1",
            status=ApplicationStatus.TAILORED,
        )
        defaults.update(kwargs)
        return ApplicationRecord(**defaults)

    def test_save_and_load(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = self._record()
        tracker.save_application(record)
        loaded = tracker.get_application(record.application_id)
        assert loaded is not None
        assert loaded.application_id == record.application_id
        assert loaded.status == ApplicationStatus.TAILORED

    def test_list_applications_returns_all_saved(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        r1 = self._record()
        r2 = self._record()
        tracker.save_application(r1)
        tracker.save_application(r2)
        records = tracker.list_applications()
        ids = {r.application_id for r in records}
        assert r1.application_id in ids
        assert r2.application_id in ids

    def test_list_applications_empty_when_none_saved(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        assert tracker.list_applications() == []

    def test_get_application_returns_none_when_not_found(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        assert tracker.get_application("does-not-exist") is None

    def test_update_status_persists_new_status(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = self._record(status=ApplicationStatus.TAILORED)
        tracker.save_application(record)
        updated = tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        assert updated.status == ApplicationStatus.APPLIED
        reloaded = tracker.get_application(record.application_id)
        assert reloaded.status == ApplicationStatus.APPLIED

    def test_update_status_sets_applied_at_for_applied(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = self._record(status=ApplicationStatus.TAILORED)
        tracker.save_application(record)
        updated = tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        assert updated.applied_at is not None

    def test_update_status_clears_applied_at_when_reverting_to_tailored(self, tmp_path):
        """If a user moves a record back to TAILORED, applied_at is cleared."""
        tracker = _make_tracker(tmp_path)
        record = self._record(status=ApplicationStatus.TAILORED)
        tracker.save_application(record)
        tracker.update_status(record.application_id, ApplicationStatus.APPLIED)
        reverted = tracker.update_status(record.application_id, ApplicationStatus.TAILORED)
        assert reverted.applied_at is None

    def test_update_status_raises_for_unknown_id(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="No application found"):
            tracker.update_status("ghost-id", ApplicationStatus.APPLIED)

    def test_save_application_returns_the_record(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        record = self._record()
        returned = tracker.save_application(record)
        assert returned is record


# ---------------------------------------------------------------------------
# Tests for pure UI helpers in app.ui.views.tailoring_page
# (import path verified on disk: app/ui/views/tailoring_page.py)
# ---------------------------------------------------------------------------

class TestArtifactSignature:
    """Tests for _artifact_signature() — stable key for duplicate-save guard."""

    def test_signature_includes_resume_id(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="resume-abc")
        sig = _artifact_signature(resume, None)
        assert "resume-abc" in sig

    def test_signature_with_no_cover_letter_contains_none(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="r1")
        sig = _artifact_signature(resume, None)
        assert "none" in sig

    def test_signature_with_cover_letter_includes_draft_id(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl-xyz")
        sig = _artifact_signature(resume, cl)
        assert "r1" in sig
        assert "cl-xyz" in sig

    def test_same_artifacts_produce_same_signature(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        assert _artifact_signature(resume, cl) == _artifact_signature(resume, cl)

    def test_different_resume_produces_different_signature(self):
        from app.ui.views.tailoring_page import _artifact_signature
        r1 = _resume(resume_id="r1")
        r2 = _resume(resume_id="r2")
        assert _artifact_signature(r1, None) != _artifact_signature(r2, None)

    def test_different_cover_letter_produces_different_signature(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="r1")
        cl1 = _cover_letter(draft_id="cl1")
        cl2 = _cover_letter(draft_id="cl2")
        assert _artifact_signature(resume, cl1) != _artifact_signature(resume, cl2)

    def test_no_cl_vs_with_cl_produces_different_signature(self):
        from app.ui.views.tailoring_page import _artifact_signature
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        assert _artifact_signature(resume, None) != _artifact_signature(resume, cl)


class TestCheckApprovalReadiness:
    """Tests for _check_approval_readiness() — returns blocking reasons list."""

    def test_empty_when_resume_passes_and_no_cl(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        assert _check_approval_readiness(resume, _passing_report("r1"), None, None) == []

    def test_empty_when_both_pass(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        assert _check_approval_readiness(
            resume, _passing_report("r1"), cl, _passing_report("cl1")
        ) == []

    def test_blocked_when_resume_report_is_none(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        reasons = _check_approval_readiness(resume, None, None, None)
        assert len(reasons) == 1
        assert "not been run" in reasons[0]

    def test_blocked_when_resume_report_has_wrong_artifact_id(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        wrong = _passing_report("wrong-id")
        reasons = _check_approval_readiness(resume, wrong, None, None)
        assert len(reasons) == 1
        assert "stale" in reasons[0].lower()

    def test_blocked_when_resume_report_failed(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        failed = _failing_report("r1")
        reasons = _check_approval_readiness(resume, failed, None, None)
        assert len(reasons) == 1
        assert "failed" in reasons[0].lower()

    def test_blocked_when_cl_report_is_none(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        reasons = _check_approval_readiness(resume, _passing_report("r1"), cl, None)
        assert len(reasons) == 1
        assert "cover letter" in reasons[0].lower()

    def test_blocked_when_cl_report_has_wrong_artifact_id(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        wrong_cl = _passing_report("wrong-cl")
        reasons = _check_approval_readiness(resume, _passing_report("r1"), cl, wrong_cl)
        assert len(reasons) == 1
        assert "stale" in reasons[0].lower()

    def test_blocked_when_cl_report_failed(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        reasons = _check_approval_readiness(
            resume, _passing_report("r1"), cl, _failing_report("cl1")
        )
        assert len(reasons) == 1
        assert "failed" in reasons[0].lower()

    def test_multiple_blocking_reasons_returned(self):
        from app.ui.views.tailoring_page import _check_approval_readiness
        resume = _resume(resume_id="r1")
        cl = _cover_letter(draft_id="cl1")
        # Resume report missing + CL report missing → two blocking reasons
        reasons = _check_approval_readiness(resume, None, cl, None)
        assert len(reasons) == 2

"""
Application approval pipeline — Slice 8.

Entry point: approve_and_save(...)

Responsibilities:
  1. Enforce the approval gate:
     - resume is required
     - resume_report must exist, must match resume.resume_id, and must have passed
     - if a cover letter draft exists, cl_report must exist, must match cl.draft_id,
       and must have passed
  2. Rebuild the TailoredResume with approved=True / approved_at via model_validate.
  3. Persist the approved resume (and optional cover letter) through the Repository.
  4. Create and save an ApplicationRecord (status=TAILORED) via TrackerService.
  5. Return the ApplicationRecord exactly as returned by TrackerService.save_application.

Partial-persistence note: artifacts are saved to the repo before the tracker record
is written. If tracker.save_application raises after artifact saves, the artifacts
will be orphaned in the repo but no ApplicationRecord will exist. The Repository
interface does not support rollback in V1; this is an acceptable risk for a single-user
local store.

This module does not:
  - call the LLM
  - generate or modify generated content
  - redesign validation logic
  - send external requests
  - auto-submit applications
"""
from __future__ import annotations

import logging

from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord, ApplicationStatus
from app.schemas.tailoring import CoverLetterDraft, TailoredResume
from app.schemas.validation import ValidationReport
from app.storage.repository import Repository
from app.utils.ids import generate_id
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

_RESUME_COLLECTION = "tailored_resumes"
_COVER_LETTER_COLLECTION = "cover_letters"


class ApprovalError(Exception):
    """Raised when an approval gate condition is not met."""


def approve_and_save(
    resume: TailoredResume | None,
    cl: CoverLetterDraft | None,
    resume_report: ValidationReport | None,
    cl_report: ValidationReport | None,
    tracker: TrackerService,
    repo: Repository,
) -> ApplicationRecord:
    """
    Enforce the approval gate, persist artifacts, and create an ApplicationRecord.

    Args:
        resume:        The tailored resume to approve. Required.
        cl:            Optional cover letter draft. Must pass validation if present.
        resume_report: Validation report for the resume. Must exist, must match
                       resume.resume_id, and must have passed.
        cl_report:     Validation report for the cover letter. Required if cl is
                       not None; must match cl.draft_id and must have passed.
        tracker:       TrackerService used to save the ApplicationRecord.
        repo:          Repository used to persist approved artifacts.

    Returns:
        The ApplicationRecord exactly as returned by tracker.save_application().

    Raises:
        ApprovalError: if any gate condition is not satisfied.
    """
    # --- Gate 1: Resume is required ---
    if resume is None:
        raise ApprovalError(
            "A tailored resume is required for approval. "
            "Generate a resume from the Tailoring Studio first."
        )

    # --- Gate 2: Resume validation must exist, match this resume, and have passed ---
    if resume_report is None:
        raise ApprovalError(
            "Resume validation is required before approval. "
            "Run 'Validate Resume Draft' first."
        )
    if resume_report.artifact_id != resume.resume_id:
        raise ApprovalError(
            "Resume validation report does not match the current resume draft. "
            "Re-run 'Validate Resume Draft' before approving."
        )
    if not resume_report.passed:
        raise ApprovalError(
            "Resume validation failed — critical issues must be resolved before approval. "
            "Review the validation flags and regenerate if necessary."
        )

    # --- Gate 3: Cover letter validation required if a CL draft is present ---
    if cl is not None:
        if cl_report is None:
            raise ApprovalError(
                "Cover letter validation is required before approval because a cover letter "
                "draft is present. Run 'Validate Cover Letter Draft' first."
            )
        if cl_report.artifact_id != cl.draft_id:
            raise ApprovalError(
                "Cover letter validation report does not match the current cover letter draft. "
                "Re-run 'Validate Cover Letter Draft' before approving."
            )
        if not cl_report.passed:
            raise ApprovalError(
                "Cover letter validation failed — critical issues must be resolved before approval. "
                "Review the validation flags and regenerate if necessary."
            )

    # --- Rebuild resume with approved=True via full model_validate ---
    now = utc_now()
    resume_data = resume.model_dump(mode="json")
    resume_data["approved"] = True
    resume_data["approved_at"] = now.isoformat()
    approved_resume = TailoredResume.model_validate(resume_data)

    # --- Persist approved artifacts ---
    repo.save(
        _RESUME_COLLECTION,
        approved_resume.resume_id,
        approved_resume.model_dump(mode="json"),
    )
    logger.info("Persisted approved resume '%s'", approved_resume.resume_id)

    if cl is not None:
        repo.save(
            _COVER_LETTER_COLLECTION,
            cl.draft_id,
            cl.model_dump(mode="json"),
        )
        logger.info("Persisted cover letter '%s'", cl.draft_id)

    # --- Create and save ApplicationRecord; return exactly what tracker saved ---
    record = ApplicationRecord(
        application_id=generate_id(),
        job_id=approved_resume.job_id,
        candidate_id=approved_resume.candidate_id,
        resume_id=approved_resume.resume_id,
        status=ApplicationStatus.TAILORED,
    )
    saved = tracker.save_application(record)
    logger.info(
        "Created application record '%s' for job '%s'",
        record.application_id,
        record.job_id,
    )
    return saved

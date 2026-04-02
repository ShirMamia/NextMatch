"""
Tailoring Studio page — Slices 5, 6, 7, and 8.

Slice 5 scope (complete): candidate-job fit analysis.
Slice 6 scope (complete): tailored resume and cover letter generation.
Slice 7 scope (complete): validation of generated drafts.
Slice 8 scope (complete): approval gate and save to application tracker.

Page structure:
  1. Empty-state guards — profile and job must both be present.
  2. Slice 5 — candidate-job fit analysis (match score, skill detail, gaps, strengths).
  3. Slice 6 — generation area (tailored resume draft + cover letter draft).
  4. Slice 7 — validation area (validate generated drafts, display ValidationReport).
  5. Slice 8 — approval area (gate status, Approve and Save button, tracker link).

Approval rules:
  - Requires a TailoredResume in session state.
  - Requires a passing resume ValidationReport whose artifact_id matches the current resume.
  - If a CoverLetterDraft exists, also requires a passing cover letter ValidationReport
    whose artifact_id matches the current draft.
  - Approval readiness is evaluated from the current session state on every render.
  - The duplicate-save guard only fires when current validation is still valid for
    the exact same artifact set that was previously approved.
  - Re-running validation always clears prior approval UI state so that any change in
    validation results is reflected before the user can re-approve.
  - Stale approval state is also cleared when the job, candidate, or drafts change.
  - All approval and persistence logic delegates to the application pipeline and
    TrackerService; this page is a thin UI shell only.

Session state keys managed here (in addition to those from Slices 5–7):
  saved_application_record    — ApplicationRecord returned from a successful approval
  approved_artifact_signature — artifact signature string at the time of approval

All matching logic lives in app/matching/. All generation logic lives in app/generation/.
All validation logic lives in app/validation/. All approval/save logic lives in
app/orchestration/ and app/reporting/. This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.generation.cover_letter_generator import generate_cover_letter
from app.generation.resume_tailor import generate_tailored_resume
from app.matching.matcher import compute_match
from app.orchestration.application_pipeline import ApprovalError, approve_and_save
from app.reporting.tracker import TrackerService
from app.schemas.application import ApplicationRecord
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult
from app.schemas.tailoring import CoverLetterDraft, TailoredResume
from app.schemas.validation import ValidationReport
from app.services.config import get_config
from app.services.llm_client import LLMParseError
from app.storage.file_store import FileStore
from app.ui.components import evidence_panel, validation_panel
from app.validation.validator import validate_cover_letter, validate_resume


def render() -> None:
    st.header("Tailoring Studio")

    profile: CandidateProfile | None = st.session_state.get("candidate_profile")
    job: JobPosting | None = st.session_state.get("selected_job")

    # --- Empty-state guards ---
    if profile is None and job is None:
        st.info(
            "To use Tailoring Studio:\n\n"
            "1. Go to **Candidate Profile** and upload your CV.\n"
            "2. Go to **Discover Jobs**, ingest a job, and select it."
        )
        return

    if profile is None:
        st.warning(
            "No candidate profile loaded. "
            "Go to **Candidate Profile** to upload and parse your CV."
        )
        return

    if job is None:
        st.warning(
            "No job selected. "
            "Go to **Discover Jobs**, ingest a job, and select it from the list."
        )
        return

    # --- Both exist: match analysis → generation → validation → approval ---
    _render_match_analysis(profile, job)
    _render_generation_section(profile, job)
    _render_validation_section()
    _render_approval_section()


# ---------------------------------------------------------------------------
# Slice 5 — Match analysis
# ---------------------------------------------------------------------------

def _render_match_analysis(profile: CandidateProfile, job: JobPosting) -> None:
    """Compute and display the candidate-job fit for the selected job."""

    # Use session-state cache: only recompute when the job or candidate changes.
    cached: MatchResult | None = st.session_state.get("match_result")
    if (
        cached is None
        or cached.job_id != job.job_id
        or cached.candidate_id != profile.candidate_id
    ):
        with st.spinner("Computing candidate-job fit\u2026"):
            result = compute_match(profile, job)
        st.session_state.match_result = result
    else:
        result = cached

    st.subheader(f"Match: {profile.name} \u2192 {job.title} at {job.company}")

    # Clarify the distinction between the two fit concepts.
    st.caption(
        "\u26a0\ufe0f **Candidate-job fit** \u2014 how well your background matches this job's requirements. "
        "This is separate from the **search-profile fit** score shown on the Discover Jobs page."
    )

    # --- Overall score ---
    total_pct = int(result.score_breakdown.overall_score * 100)
    st.metric("Overall candidate-job fit", f"{total_pct}%")

    # --- Factor breakdown ---
    with st.expander("Score breakdown", expanded=True):
        _render_score_breakdown(result)

    # --- Skill-level detail ---
    st.divider()
    _render_skill_detail(result)

    # --- Strengths ---
    if result.strengths:
        st.divider()
        st.markdown("**Strengths**")
        for s in result.strengths:
            st.markdown(f"- {s}")

    # --- Gaps ---
    if result.gaps:
        st.divider()
        st.markdown("**Gaps**")
        for g in result.gaps:
            st.markdown(f"- {g}")

    # --- Recommendations ---
    if result.recommendations:
        st.divider()
        st.markdown("**Recommendations**")
        for r in result.recommendations:
            st.markdown(f"- {r}")


def _render_score_breakdown(result: MatchResult) -> None:
    """Display per-factor scores as a table of metrics."""
    bd = result.score_breakdown

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Skills", f"{int(bd.skills_score * 100)}%")
        st.caption("Required + preferred skill coverage")
    with col2:
        st.metric("Experience", f"{int(bd.experience_score * 100)}%")
        st.caption("Work history depth and title relevance")
    with col3:
        st.metric("Seniority", f"{int(bd.seniority_score * 100)}%")
        st.caption("Apparent seniority vs. job requirement")
    with col4:
        st.metric("Education", f"{int(bd.education_score * 100)}%")
        st.caption("Education presence and field relevance")


def _render_skill_detail(result: MatchResult) -> None:
    """Display the matched and missing skill tags from the job requirements."""
    if not result.skill_matches:
        st.caption("No structured skill tags found in this job posting.")
        return

    matched = [sm for sm in result.skill_matches if sm.found_in_profile]
    missing = [sm for sm in result.skill_matches if not sm.found_in_profile]

    col_matched, col_missing = st.columns(2)
    with col_matched:
        st.markdown(f"**Skills found in profile** ({len(matched)})")
        if matched:
            for sm in matched:
                st.markdown(f"- `{sm.skill}`")
        else:
            st.caption("None of the job's skill tags were found in your profile.")

    with col_missing:
        st.markdown(f"**Skills not found in profile** ({len(missing)})")
        if missing:
            for sm in missing:
                st.markdown(f"- `{sm.skill}`")
        else:
            st.caption("All skill tags from the job posting were found in your profile.")


# ---------------------------------------------------------------------------
# Slice 6 — Generation (tailored resume + cover letter)
# ---------------------------------------------------------------------------

def _render_generation_section(profile: CandidateProfile, job: JobPosting) -> None:
    """Render the Slice 6 generation area below the Slice 5 match analysis."""
    st.divider()
    st.subheader("Resume Generation")
    st.caption(
        "\u26a0\ufe0f **Preview only.** Generated content is not saved until approved. "
        "Validate your draft below, then use the **Approve and Save** section to persist it."
    )

    match_result: MatchResult | None = st.session_state.get("match_result")
    if match_result is None:
        st.info("Match analysis must complete before generation is available.")
        return

    # --- Invalidate cached artifacts if job or candidate changed ---
    _clear_stale_generation_cache(profile, job)

    # --- Tailored resume ---
    st.markdown("#### Tailored Resume Draft")
    if st.button("Generate Tailored Resume", key="btn_generate_resume"):
        with st.spinner("Generating tailored resume\u2026"):
            try:
                resume = generate_tailored_resume(profile, job, match_result)
                st.session_state.tailored_resume = resume
                # New resume: clear validation and any previous approval state.
                st.session_state.resume_validation = None
                _clear_saved_approval_state()
            except LLMParseError as exc:
                st.error(f"Resume generation failed (LLM parse error): {exc}")
            except Exception as exc:
                st.error(f"Resume generation failed: {exc}")

    resume: TailoredResume | None = st.session_state.get("tailored_resume")
    if resume is not None:
        _render_tailored_resume(resume)

    st.divider()

    # --- Cover letter ---
    st.markdown("#### Cover Letter Draft")
    if st.button("Generate Cover Letter", key="btn_generate_cover_letter"):
        with st.spinner("Generating cover letter\u2026"):
            try:
                cl = generate_cover_letter(profile, job, match_result)
                st.session_state.cover_letter_draft = cl
                # New cover letter: clear validation and any previous approval state.
                st.session_state.cover_letter_validation = None
                _clear_saved_approval_state()
            except ValueError as exc:
                st.error(f"Cannot generate cover letter: {exc}")
            except LLMParseError as exc:
                st.error(f"Cover letter generation failed (LLM parse error): {exc}")
            except Exception as exc:
                st.error(f"Cover letter generation failed: {exc}")

    cl: CoverLetterDraft | None = st.session_state.get("cover_letter_draft")
    if cl is not None:
        _render_cover_letter(cl)


def _clear_stale_generation_cache(profile: CandidateProfile, job: JobPosting) -> None:
    """Clear cached generation artifacts, validation, and approval state when job or candidate changed."""
    resume: TailoredResume | None = st.session_state.get("tailored_resume")
    if resume is not None and (
        resume.job_id != job.job_id or resume.candidate_id != profile.candidate_id
    ):
        st.session_state.tailored_resume = None
        st.session_state.cover_letter_draft = None
        st.session_state.resume_validation = None
        st.session_state.cover_letter_validation = None
        _clear_saved_approval_state()
        st.info("Job or candidate changed — previous drafts, validation, and approval state cleared.")
        return

    cl: CoverLetterDraft | None = st.session_state.get("cover_letter_draft")
    if cl is not None and (
        cl.job_id != job.job_id or cl.candidate_id != profile.candidate_id
    ):
        st.session_state.cover_letter_draft = None
        st.session_state.cover_letter_validation = None
        _clear_saved_approval_state()


def _clear_saved_approval_state() -> None:
    """Clear approval UI state so the approval section re-evaluates from scratch.

    Called whenever generation or validation state changes materially:
    - new resume generated
    - new cover letter generated
    - resume validation re-run
    - cover letter validation re-run
    - job or candidate changed
    """
    st.session_state.saved_application_record = None
    st.session_state.approved_artifact_signature = None


def _render_tailored_resume(resume: TailoredResume) -> None:
    """Display the generated TailoredResume with inline source evidence."""
    # Summary
    if resume.summary.text:
        st.markdown("**Professional Summary**")
        st.markdown(resume.summary.text)
        if resume.summary.evidence_links:
            with st.expander("Summary — source evidence", expanded=False):
                for ev in resume.summary.evidence_links:
                    st.caption(
                        f"Section: `{ev.source_section}` | "
                        f"Confidence: {int(ev.confidence * 100)}%"
                    )
                    st.text(ev.source_bullet)
        st.write("")

    # Experience sections
    if not resume.sections:
        st.caption("No work experience bullets to display.")
        return

    for section_name, bullets in resume.sections.items():
        # Strip the index prefix for display: "work_experience[0] — Acme — Engineer"
        # → "Acme — Engineer"
        display_name = section_name.split(" — ", maxsplit=1)[-1] if " — " in section_name else section_name
        st.markdown(f"**{display_name}**")
        evidence_panel.render(bullets)
        st.write("")


def _render_cover_letter(cl: CoverLetterDraft) -> None:
    """Display the generated cover letter draft with its evidence links."""
    st.markdown(cl.body)

    if cl.evidence_links:
        with st.expander("Cover letter — source evidence", expanded=False):
            for ev in cl.evidence_links:
                st.caption(f"Section: `{ev.source_section}`")
                st.text(ev.source_bullet)


# ---------------------------------------------------------------------------
# Slice 7 — Validation
# ---------------------------------------------------------------------------

def _render_validation_section() -> None:
    """Render the Slice 7 validation area below the generated drafts."""
    st.divider()
    st.subheader("Draft Validation")
    st.caption(
        "\u26a0\ufe0f **Validation is a review gate.** "
        "Critical flags must be resolved before approval is allowed. "
        "Validation does not modify any generated content."
    )

    resume: TailoredResume | None = st.session_state.get("tailored_resume")
    cl: CoverLetterDraft | None = st.session_state.get("cover_letter_draft")

    if resume is None and cl is None:
        st.info("Generate a tailored resume or cover letter above to enable validation.")
        return

    # --- Resume validation ---
    if resume is not None:
        st.markdown("#### Validate Tailored Resume")
        if st.button("Validate Resume Draft", key="btn_validate_resume"):
            with st.spinner("Validating resume draft\u2026"):
                report = validate_resume(resume)
                st.session_state.resume_validation = report
                # Re-running validation always clears prior approval UI state so
                # any change in results is reflected before the user can re-approve.
                _clear_saved_approval_state()

        resume_report: ValidationReport | None = st.session_state.get("resume_validation")
        if resume_report is not None:
            validation_panel.render(resume_report)

    # --- Cover letter validation ---
    if cl is not None:
        st.markdown("#### Validate Cover Letter")
        if st.button("Validate Cover Letter Draft", key="btn_validate_cover_letter"):
            with st.spinner("Validating cover letter draft\u2026"):
                report = validate_cover_letter(cl)
                st.session_state.cover_letter_validation = report
                # Same as above: clear prior approval UI state on re-validation.
                _clear_saved_approval_state()

        cl_report: ValidationReport | None = st.session_state.get("cover_letter_validation")
        if cl_report is not None:
            validation_panel.render(cl_report)


# ---------------------------------------------------------------------------
# Slice 8 — Approval and Save
# ---------------------------------------------------------------------------

def _artifact_signature(resume: TailoredResume, cl: CoverLetterDraft | None) -> str:
    """Return a stable string key for the current artifact set.

    Used to detect whether the same resume+cover-letter combination has already
    been approved this session. The signature changes whenever a new resume or
    new cover letter is generated, preventing duplicate saves.
    """
    cl_part = cl.draft_id if cl is not None else "none"
    return f"{resume.resume_id}:{cl_part}"


def _check_approval_readiness(
    resume: TailoredResume,
    resume_report: ValidationReport | None,
    cl: CoverLetterDraft | None,
    cl_report: ValidationReport | None,
) -> list[str]:
    """Return a list of human-readable blocking reasons.

    An empty list means all gate conditions are satisfied and approval may proceed.
    The pipeline enforces these same rules; this function is for UI feedback only.
    """
    blocking: list[str] = []

    if resume_report is None:
        blocking.append(
            "Resume validation has not been run \u2014 click **Validate Resume Draft** above."
        )
    elif resume_report.artifact_id != resume.resume_id:
        blocking.append(
            "Resume validation report is stale (artifact ID mismatch). "
            "Re-run **Validate Resume Draft** after any regeneration."
        )
    elif not resume_report.passed:
        blocking.append(
            "Resume validation failed \u2014 resolve all critical flags before approving."
        )

    if cl is not None:
        if cl_report is None:
            blocking.append(
                "Cover letter validation has not been run \u2014 "
                "click **Validate Cover Letter Draft** above."
            )
        elif cl_report.artifact_id != cl.draft_id:
            blocking.append(
                "Cover letter validation report is stale (artifact ID mismatch). "
                "Re-run **Validate Cover Letter Draft** after any regeneration."
            )
        elif not cl_report.passed:
            blocking.append(
                "Cover letter validation failed \u2014 resolve all critical flags before approving."
            )

    return blocking


def _render_approval_section() -> None:
    """Render the Slice 8 approval gate and Approve and Save button."""
    resume: TailoredResume | None = st.session_state.get("tailored_resume")
    if resume is None:
        return

    cl: CoverLetterDraft | None = st.session_state.get("cover_letter_draft")
    resume_report: ValidationReport | None = st.session_state.get("resume_validation")
    cl_report: ValidationReport | None = st.session_state.get("cover_letter_validation")

    st.divider()
    st.subheader("Approve and Save")
    st.caption(
        "Approval persists the validated artifacts and creates a record in the "
        "**Application Tracker**. No content is modified during approval. "
        "Once saved, the record can be managed from the Tracker page."
    )

    # --- Evaluate current readiness first ---
    # This must happen before the duplicate-save guard so that stale or failing
    # validation state is always surfaced, even when a prior approval exists.
    blocking = _check_approval_readiness(resume, resume_report, cl, cl_report)
    if blocking:
        st.warning("**Approval is not ready.** Resolve the following before saving:")
        for reason in blocking:
            st.markdown(f"- {reason}")
        return

    # --- Current validation is valid: now check for duplicate saves ---
    # Only show "already approved" when validation is still passing AND the
    # exact same artifact set was approved this session. If the user re-ran
    # validation after a prior approval, _clear_saved_approval_state() would
    # have already cleared the saved record (called inside the validation buttons),
    # so this guard will not fire for stale approval state.
    current_sig = _artifact_signature(resume, cl)
    saved_record: ApplicationRecord | None = st.session_state.get("saved_application_record")
    approved_sig: str | None = st.session_state.get("approved_artifact_signature")

    if saved_record is not None and approved_sig == current_sig:
        st.success(
            f"Already approved and saved. "
            f"Application ID: `{saved_record.application_id[:8]}\u2026` "
            f"| Status: **{saved_record.status.value}**"
        )
        st.info("View and manage this application on the **Application Tracker** page.")
        return

    # --- All clear: show Approve and Save button ---
    st.success("All validation checks passed \u2014 ready to approve.")

    if st.button("Approve and Save", key="btn_approve_and_save", type="primary"):
        with st.spinner("Saving approved artifacts\u2026"):
            try:
                cfg = get_config()
                store = FileStore(cfg.data_dir)
                tracker = TrackerService(store)
                record = approve_and_save(
                    resume, cl, resume_report, cl_report, tracker, store
                )
                st.session_state.saved_application_record = record
                st.session_state.approved_artifact_signature = current_sig
                st.success(
                    f"Approved and saved. "
                    f"Application ID: `{record.application_id[:8]}\u2026` "
                    f"| Status: **{record.status.value}**"
                )
                st.info("View and manage this application on the **Application Tracker** page.")
            except ApprovalError as exc:
                st.error(f"Approval blocked: {exc}")
            except Exception as exc:
                st.error(f"Approval failed unexpectedly: {exc}")

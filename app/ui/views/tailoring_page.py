"""
Tailoring Studio page — Slices 5, 6, and 7.

Slice 5 scope (complete): candidate-job fit analysis.
Slice 6 scope (complete): tailored resume and cover letter generation.
Slice 7 scope (this update): validation of generated drafts.

Page structure:
  1. Empty-state guards — profile and job must both be present.
  2. Slice 5 — candidate-job fit analysis (match score, skill detail, gaps, strengths).
  3. Slice 6 — generation area (tailored resume draft + cover letter draft).
  4. Slice 7 — validation area (validate generated drafts, display ValidationReport).

Validation rules:
  - Validation is available once a draft exists in session state.
  - Validation is deterministic — no LLM calls.
  - Validation results are preview-only review flags.
  - Approval and save flow are NOT implemented here — that is Slice 8.
  - Cached validation reports are cleared when the job, candidate, or draft changes.

All matching logic lives in app/matching/. All generation logic lives in app/generation/.
All validation logic lives in app/validation/. This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.generation.cover_letter_generator import generate_cover_letter
from app.generation.resume_tailor import generate_tailored_resume
from app.matching.matcher import compute_match
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult
from app.schemas.tailoring import CoverLetterDraft, TailoredResume
from app.schemas.validation import ValidationReport
from app.services.llm_client import LLMParseError
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

    # --- Both exist: Slice 5 match analysis, Slice 6 generation, Slice 7 validation ---
    _render_match_analysis(profile, job)
    _render_generation_section(profile, job)
    _render_validation_section(profile, job)


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
        "\u26a0\ufe0f **Preview only.** Generated content is not saved as an approved artifact. "
        "Validate your draft below, then approve it in the next step (coming in Slice 8)."
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
                # Clear any previous validation result for this artifact.
                st.session_state.resume_validation = None
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
                # Clear any previous validation result for this artifact.
                st.session_state.cover_letter_validation = None
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
    """Clear cached generation artifacts and validation results when job or candidate has changed."""
    resume: TailoredResume | None = st.session_state.get("tailored_resume")
    if resume is not None and (
        resume.job_id != job.job_id or resume.candidate_id != profile.candidate_id
    ):
        st.session_state.tailored_resume = None
        st.session_state.cover_letter_draft = None
        st.session_state.resume_validation = None
        st.session_state.cover_letter_validation = None
        st.info("Job or candidate changed — previous drafts and validation results cleared.")
        return

    cl: CoverLetterDraft | None = st.session_state.get("cover_letter_draft")
    if cl is not None and (
        cl.job_id != job.job_id or cl.candidate_id != profile.candidate_id
    ):
        st.session_state.cover_letter_draft = None
        st.session_state.cover_letter_validation = None


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

def _render_validation_section(profile: CandidateProfile, job: JobPosting) -> None:
    """Render the Slice 7 validation area below the generated drafts."""
    st.divider()
    st.subheader("Draft Validation")
    st.caption(
        "\u26a0\ufe0f **Validation is a review gate only.** "
        "Approval and save functionality will be available in the next step (Slice 8). "
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

        cl_report: ValidationReport | None = st.session_state.get("cover_letter_validation")
        if cl_report is not None:
            validation_panel.render(cl_report)

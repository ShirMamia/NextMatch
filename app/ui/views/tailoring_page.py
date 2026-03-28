"""
Tailoring Studio page — Slice 5.

Slice 5 scope: candidate-job fit analysis only.
Resume generation, validation, and approval come in later slices.

This page:
  1. Detects whether a CandidateProfile is loaded.
  2. Detects whether a JobPosting is selected.
  3. Shows clear empty states when either is missing.
  4. Computes and displays a MatchResult when both are present.
  5. Makes the distinction between Slice 4 search-profile fit and Slice 5
     candidate-job fit explicit and visible.

All matching logic lives in app/matching/. This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.matching.matcher import compute_match
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult


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

    # --- Both exist: compute match ---
    _render_match_analysis(profile, job)


# ---------------------------------------------------------------------------
# Match analysis rendering
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

    # --- Future slices placeholder ---
    st.divider()
    st.info(
        "Resume tailoring and cover letter generation will be available in Slice 6. "
        "Validation and approval gates come in Slice 7."
    )


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

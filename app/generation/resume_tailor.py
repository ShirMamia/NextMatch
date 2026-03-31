"""
Resume tailor — orchestrates generation of a TailoredResume.

Generation flow:
  1. Order work experience entries by relevance (deterministic, section_reorderer).
  2. Rewrite bullets per section (LLM, one call per bullet via bullet_rewriter).
  3. Generate a grounded summary (LLM, one call with explicit evidence sources).
  4. Assemble and return a schema-validated TailoredResume.

Section key design:
  Section keys in TailoredResume.sections use the format:
    "work_experience[{index}] — {company} — {title}"
  The index prefix guarantees uniqueness even when two entries share company/title.

This module is generation-only.
Validation and approval are separate slices (Slice 7, Slice 8).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.generation import bullet_rewriter, section_reorderer
from app.generation.prompts import (
    SUMMARY_SYSTEM,
    EvidenceSources,
    build_summary_user_prompt,
)
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult
from app.schemas.tailoring import EvidenceLink, GroundedText, TailoredResume
from app.services.llm_client import LLMParseError, call_llm_structured
from app.utils.ids import generate_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal LLM response schema for summary generation
# ---------------------------------------------------------------------------

class _SummaryResponse(BaseModel):
    """Internal schema for the LLM summary generation response."""

    model_config = {"extra": "forbid"}

    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_indices: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence source builder for summary
# ---------------------------------------------------------------------------

def _build_summary_evidence_sources(profile: CandidateProfile) -> EvidenceSources:
    """Assemble the numbered evidence source list for summary generation.

    Sources are profile-native only: no derived outputs (e.g. match strengths)
    are included. Every EvidenceLink produced from these sources points back to
    verbatim candidate profile material.

    Each entry is (section_key, source_text). The model references these by
    1-based index; callers map the returned indices back to EvidenceLink objects.
    """
    sources: EvidenceSources = []

    if profile.summary.strip():
        sources.append(("profile.summary", profile.summary))

    if profile.skills:
        sources.append(("profile.skills", ", ".join(profile.skills[:15])))

    for i, edu in enumerate(profile.education):
        edu_text = f"{edu.degree} in {edu.field}, {edu.institution}"
        sources.append((f"education[{i}]", edu_text))

    return sources


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def _generate_summary(
    profile: CandidateProfile,
    job: JobPosting,
) -> GroundedText:
    """Generate a job-targeted summary grounded in the candidate's profile.

    Evidence sources are profile-native only (profile.summary, profile.skills,
    education). Derived outputs such as match strengths are not used as evidence.

    If the candidate has no existing summary, returns an empty GroundedText
    rather than generating unsupported content.
    Falls back to the existing summary on LLM parse failure.
    """
    if not profile.summary.strip():
        return GroundedText(text="")

    evidence_sources = _build_summary_evidence_sources(profile)
    if not evidence_sources:
        return GroundedText(text=profile.summary)

    user_prompt = build_summary_user_prompt(
        job_title=job.title,
        company=job.company,
        evidence_sources=evidence_sources,
    )

    try:
        response = call_llm_structured(
            system_prompt=SUMMARY_SYSTEM,
            user_prompt=user_prompt,
            response_model=_SummaryResponse,
            max_tokens=512,
        )
        summary_text = response.summary.strip() or profile.summary
        confidence = response.confidence
        returned_indices = response.evidence_indices
    except LLMParseError as exc:
        logger.warning("Summary generation failed — using existing summary. Error: %s", exc)
        summary_text = profile.summary
        confidence = 0.0
        returned_indices = [1] if evidence_sources else []

    # Map returned 1-based indices to EvidenceLink objects.
    evidence_links: list[EvidenceLink] = []
    for idx in returned_indices:
        if 1 <= idx <= len(evidence_sources):
            section_key, source_text = evidence_sources[idx - 1]
            evidence_links.append(
                EvidenceLink(
                    source_bullet=source_text,
                    source_section=section_key,
                    confidence=confidence,
                )
            )

    # Fallback: if no valid indices were returned, link to profile.summary.
    if not evidence_links and profile.summary.strip():
        evidence_links.append(
            EvidenceLink(
                source_bullet=profile.summary,
                source_section="profile.summary",
                confidence=confidence,
            )
        )

    return GroundedText(text=summary_text, evidence_links=evidence_links)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_tailored_resume(
    profile: CandidateProfile,
    job: JobPosting,
    match_result: MatchResult,
) -> TailoredResume:
    """Generate a structured TailoredResume from profile, job, and match result.

    Generation is preview-only. Validation happens in Slice 7; approval in Slice 8.

    Section keys use the format "work_experience[{index}] — {company} — {title}"
    to guarantee uniqueness regardless of duplicate company/title combinations.

    Args:
        profile: The candidate's parsed profile.
        job: The selected job posting.
        match_result: The candidate-job fit result from Slice 5.

    Returns:
        A fully populated TailoredResume (schema-validated, unapproved).
    """
    # 1. Order work experience entries by relevance (deterministic).
    ordered_experience = section_reorderer.order_work_experience(profile, job)

    # Build a stable index map by object identity so section_ref paths are correct.
    exp_to_index: dict[int, int] = {
        id(exp): i for i, exp in enumerate(profile.work_experience)
    }

    # 2. Rewrite bullets per section (LLM calls).
    sections: dict[str, list] = {}
    for exp in ordered_experience:
        if not exp.bullets:
            continue
        section_index = exp_to_index.get(id(exp), 0)
        section_ref = f"work_experience[{section_index}]"
        # Collision-safe key: index prefix + company + title.
        section_name = f"work_experience[{section_index}] — {exp.company} — {exp.title}"

        tailored_bullets = bullet_rewriter.rewrite_bullets(
            bullets=exp.bullets,
            section_ref=section_ref,
            job=job,
        )
        if tailored_bullets:
            sections[section_name] = tailored_bullets

    # 3. Generate grounded summary (LLM call, profile sources only).
    summary = _generate_summary(profile, job)

    return TailoredResume(
        resume_id=generate_id(),
        candidate_id=profile.candidate_id,
        job_id=job.job_id,
        match_id=match_result.match_id,
        summary=summary,
        sections=sections,
    )

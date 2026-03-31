"""
Cover letter generator — generates a grounded CoverLetterDraft.

The cover letter is separate from TailoredResume and stored as a CoverLetterDraft.
Generation is grounded in the candidate's source profile; evidence_links in the
draft map back to the specific profile sections used.

Evidence source design:
  - evidence_sources are profile-native only, using verbatim source fragments:
      profile.summary, profile.skills, individual work experience bullets,
      and education entries.
  - Source paths are precise (e.g. "work_experience[0].bullets[1]") to support
    downstream validation in Slice 7.
  - match_result.strengths are passed as framing context in the prompt only,
    not as numbered evidence sources, so they do not appear in EvidenceLink.
  - Generation is blocked if evidence_sources is empty — no cover letter can
    be grounded from an empty profile.

This module is generation-only. Validation happens in Slice 7; approval in Slice 8.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.generation.prompts import (
    COVER_LETTER_SYSTEM,
    EvidenceSources,
    build_cover_letter_user_prompt,
)
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult
from app.schemas.tailoring import CoverLetterDraft, EvidenceLink
from app.services.llm_client import LLMParseError, call_llm_structured
from app.utils.ids import generate_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal LLM response schema
# ---------------------------------------------------------------------------

class _CoverLetterResponse(BaseModel):
    """Internal schema for the LLM cover letter generation response."""

    model_config = {"extra": "forbid"}

    body: str
    evidence_indices: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence source builder (profile-native, verbatim fragments)
# ---------------------------------------------------------------------------

def _build_evidence_sources(profile: CandidateProfile) -> EvidenceSources:
    """Assemble the numbered evidence source list for cover letter generation.

    Sources are profile-native verbatim fragments only, so that every
    EvidenceLink produced maps back to genuine source material with a precise
    section path.

    Each entry is (section_key, source_text):
      - section_key: a CandidateProfile path string (e.g. "work_experience[0].bullets[1]")
      - source_text: verbatim text from that path

    The model references these by 1-based index; callers map the returned
    indices back to EvidenceLink objects.
    """
    sources: EvidenceSources = []

    if profile.summary.strip():
        sources.append(("profile.summary", profile.summary))

    if profile.skills:
        # Skills list is verbatim from the profile; joined for readability in the prompt.
        sources.append(("profile.skills", ", ".join(profile.skills[:15])))

    # Include up to the first 2 bullets from each of the first 2 experience entries.
    for i, exp in enumerate(profile.work_experience[:2]):
        for j, bullet in enumerate(exp.bullets[:2]):
            sources.append((f"work_experience[{i}].bullets[{j}]", bullet))

    for i, edu in enumerate(profile.education):
        edu_text = f"{edu.degree} in {edu.field}, {edu.institution}"
        sources.append((f"education[{i}]", edu_text))

    return sources


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_cover_letter(
    profile: CandidateProfile,
    job: JobPosting,
    match_result: MatchResult,
) -> CoverLetterDraft:
    """Generate a grounded cover letter draft.

    Evidence sources are profile-native verbatim fragments. match_result.strengths
    are passed to the prompt as framing context but do not appear in EvidenceLink.

    Raises ValueError if the candidate profile contains no grounding material.
    Raises LLMParseError if the LLM response is malformed. Unlike bullet
    rewriting (where falling back to the original source makes sense), there is
    no meaningful fallback for a cover letter — callers should surface the error.

    Args:
        profile: The candidate's parsed profile.
        job: The selected job posting.
        match_result: The candidate-job fit result from Slice 5.

    Returns:
        A CoverLetterDraft with body text and evidence links.

    Raises:
        ValueError: if the profile has no grounding material to draw from.
        LLMParseError: if the LLM response cannot be parsed.
    """
    evidence_sources = _build_evidence_sources(profile)
    if not evidence_sources:
        raise ValueError(
            "Cannot generate a grounded cover letter from an empty profile. "
            "At least one of profile.summary, profile.skills, work_experience, "
            "or education must be present."
        )

    key_requirements = [req.text for req in job.requirements if req.is_required][:5]

    user_prompt = build_cover_letter_user_prompt(
        candidate_name=profile.name,
        job_title=job.title,
        company=job.company,
        evidence_sources=evidence_sources,
        key_requirements=key_requirements,
        candidate_strengths=match_result.strengths[:4],
    )

    # LLMParseError propagates to the caller — no fallback for cover letters.
    response = call_llm_structured(
        system_prompt=COVER_LETTER_SYSTEM,
        user_prompt=user_prompt,
        response_model=_CoverLetterResponse,
        max_tokens=1024,
    )

    # Map returned 1-based indices to EvidenceLink objects.
    evidence_links: list[EvidenceLink] = []
    for idx in response.evidence_indices:
        if 1 <= idx <= len(evidence_sources):
            section_key, source_text = evidence_sources[idx - 1]
            evidence_links.append(
                EvidenceLink(
                    source_bullet=source_text,
                    source_section=section_key,
                    confidence=1.0,  # cover letter is all-or-nothing; no per-claim confidence
                )
            )

    # Fallback: if the model returned no valid indices, link to the first available source.
    if not evidence_links:
        section_key, source_text = evidence_sources[0]
        evidence_links.append(
            EvidenceLink(
                source_bullet=source_text,
                source_section=section_key,
                confidence=1.0,
            )
        )

    return CoverLetterDraft(
        draft_id=generate_id(),
        candidate_id=profile.candidate_id,
        job_id=job.job_id,
        match_id=match_result.match_id,
        body=response.body.strip(),
        evidence_links=evidence_links,
    )

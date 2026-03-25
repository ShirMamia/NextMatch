"""
CV parser — converts raw CV text into a structured CandidateProfile.

Design:
  - LLM is called once with the cleaned CV text and a strict JSON schema prompt.
  - The LLM response is parsed and validated by Pydantic (via call_llm_structured).
  - raw_text is always set from the original (uncleaned) input, never from LLM output.
  - candidate_id and parsed_at are generated here, not by the LLM.
  - LLMParseError propagates to the caller (UI handles user-facing messaging).

The LLM is given an intermediate schema (_CVParseResult) that mirrors
CandidateProfile but excludes generated fields (candidate_id, parsed_at, raw_text).
This keeps the prompt schema honest and avoids asking the LLM to generate IDs.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.schemas.candidate import CandidateProfile, Education, WorkExperience
from app.services.llm_client import call_llm_structured
from app.utils.ids import generate_id
from app.utils.time import utc_now
from app.parsers.text_cleaner import clean_cv_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intermediate LLM-facing schema (no IDs, no raw_text, no timestamps)
# ---------------------------------------------------------------------------

class _WorkExperienceResult(BaseModel):
    """LLM-facing work experience entry. Mirrors WorkExperience without strict validators."""

    model_config = {"extra": "forbid"}

    company: str
    title: str
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)


class _EducationResult(BaseModel):
    model_config = {"extra": "forbid"}

    institution: str
    degree: str
    field: str
    graduation_year: int | None = None


class _CVParseResult(BaseModel):
    """Intermediate result from the LLM. Validated before being promoted to CandidateProfile."""

    model_config = {"extra": "forbid"}

    name: str
    email: str | None = None
    location: str | None = None
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    work_experience: list[_WorkExperienceResult] = Field(default_factory=list)
    education: list[_EducationResult] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a CV parser. Extract structured information from the CV text the user provides.

Respond with a single JSON object matching this schema exactly:
{
  "name": "string",
  "email": "string or null",
  "location": "string or null",
  "summary": "string (professional summary; use empty string if absent)",
  "skills": ["string", ...],
  "work_experience": [
    {
      "company": "string",
      "title": "string",
      "start_date": "string (e.g. '2021-03') or null",
      "end_date": "string or null",
      "is_current": true | false,
      "bullets": ["string", ...],
      "skills_used": ["string", ...]
    }
  ],
  "education": [
    {
      "institution": "string",
      "degree": "string",
      "field": "string",
      "graduation_year": integer or null
    }
  ],
  "languages": ["string", ...]
}

Rules:
- Extract only what is explicitly stated in the CV. Do not infer or invent details.
- is_current must be true only when the role is clearly marked as current (e.g. "present", "\u2013").
- If is_current is true, set end_date to null.
- start_date and end_date should follow the format "YYYY-MM" where possible. Use "YYYY" if only the year is given.
- bullets should be verbatim or near-verbatim from the CV; do not rewrite them.
- skills_used should list only skills explicitly mentioned or directly evidenced in that role's text.
- Deduplicate skills across the top-level skills list.
- Respond with JSON only. No explanation, no markdown prose outside the JSON block.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_cv(raw_text: str) -> CandidateProfile:
    """Parse raw CV text into a validated CandidateProfile.

    Args:
        raw_text: Raw CV text as uploaded or pasted by the user.
                  Preserved verbatim as raw_text on the returned profile.

    Returns:
        A fully validated CandidateProfile.

    Raises:
        ValueError: if the cleaned CV text is empty, or if ANTHROPIC_API_KEY is not set.
        LLMParseError: if the LLM response cannot be parsed or validated.
        anthropic.APIError: on API-level errors.
    """
    cleaned = clean_cv_text(raw_text)
    logger.debug("Parsing CV | raw_len=%d | cleaned_len=%d", len(raw_text), len(cleaned))

    if not cleaned:
        raise ValueError(
            "CV text is empty after cleaning. "
            "Please provide a non-empty CV file or paste CV text."
        )

    parsed: _CVParseResult = call_llm_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=cleaned,
        response_model=_CVParseResult,
    )

    # Promote to domain schema, enforcing is_current / end_date consistency.
    work_experience = [
        WorkExperience(
            company=we.company,
            title=we.title,
            start_date=we.start_date,
            end_date=None if we.is_current else we.end_date,
            is_current=we.is_current,
            bullets=we.bullets,
            skills_used=we.skills_used,
        )
        for we in parsed.work_experience
    ]
    education = [
        Education(
            institution=ed.institution,
            degree=ed.degree,
            field=ed.field,
            graduation_year=ed.graduation_year,
        )
        for ed in parsed.education
    ]

    profile = CandidateProfile(
        candidate_id=generate_id(),
        name=parsed.name,
        email=parsed.email,
        location=parsed.location,
        summary=parsed.summary,
        skills=parsed.skills,
        work_experience=work_experience,
        education=education,
        languages=parsed.languages,
        raw_text=raw_text,          # verbatim source, never LLM output
        parsed_at=utc_now(),
    )

    logger.info(
        "CV parsed | candidate_id=%s | name=%s | jobs=%d | skills=%d",
        profile.candidate_id,
        profile.name,
        len(profile.work_experience),
        len(profile.skills),
    )
    return profile

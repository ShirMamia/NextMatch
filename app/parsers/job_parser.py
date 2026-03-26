"""
Job parser — converts raw job description text into a structured JobPosting.

Design:
  - Text cleaning (whitespace, HTML) reuses clean_cv_text from text_cleaner;
    the logic is generic and equally appropriate for job description text.
  - LLM is called once with the cleaned text and a strict JSON schema prompt.
  - description_raw is always the original (uncleaned) input, never LLM output.
  - job_id and normalized_at are assigned here, not by the LLM.
  - title and company are required; ValueError is raised if either is absent.
  - The caller provides the JobSource so source metadata is explicit and accurate.
  - LLMParseError propagates to the caller (UI handles user-facing messaging).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.parsers.text_cleaner import clean_cv_text
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.services.llm_client import call_llm_structured
from app.utils.ids import generate_id
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intermediate LLM-facing schema (no IDs, no source metadata, no timestamps)
# ---------------------------------------------------------------------------

class _RequirementResult(BaseModel):
    model_config = {"extra": "forbid"}

    text: str
    is_required: bool = True
    skill_tags: list[str] = Field(default_factory=list)


class _JobParseResult(BaseModel):
    """Intermediate result from the LLM. Validated before being promoted to JobPosting."""

    model_config = {"extra": "forbid"}

    title: str | None = None
    company: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    requirements: list[_RequirementResult] = Field(default_factory=list)
    seniority_level: str | None = None
    employment_type: str | None = None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a job posting parser. Extract structured information from the job description text the user provides.

Respond with a single JSON object matching this schema exactly:
{
  "title": "string or null",
  "company": "string or null",
  "location": "string or null",
  "is_remote": true | false | null,
  "requirements": [
    {
      "text": "string",
      "is_required": true | false,
      "skill_tags": ["string", ...]
    }
  ],
  "seniority_level": "string or null",
  "employment_type": "string or null"
}

Rules:
- Extract only what is explicitly stated in the job description. Do not infer or invent details.
- title: the job title as stated. Return null if not clearly identifiable.
- company: the hiring company's name. Return null if not mentioned anywhere in the text.
- location: city and/or country as stated. Return null if not mentioned.
- is_remote: true if the posting explicitly offers remote work, false if it explicitly requires on-site, null if not specified.
- requirements: list all stated requirements and qualifications.
  - Set is_required=false for items explicitly marked as optional or secondary, using language such as: "nice to have", "bonus", "a plus", "preferred", "desired", "optional", "ideally", "advantageous".
  - Set is_required=true for everything else (default assumption for any stated requirement).
  - skill_tags: extract specific technology names, tools, or skills mentioned in that requirement (e.g. "Python", "AWS", "Kafka"). Leave empty if none are clearly named.
- seniority_level: return one of "junior", "mid", "senior", "staff", "principal", "lead" only when the seniority level is explicitly signaled by the job title or a direct statement in the description (e.g. "Senior Backend Engineer" → "senior", "Junior Developer" → "junior"). Return null if seniority is not explicitly stated.
- employment_type: return one of "full-time", "part-time", "contract", "freelance", "internship" if explicitly stated. Return null if not mentioned.
- Respond with JSON only. No explanation, no markdown prose outside the JSON block.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_job(raw_text: str, source: JobSource) -> JobPosting:
    """Parse raw job description text into a validated JobPosting.

    Args:
        raw_text: Raw job description text as uploaded or pasted by the user.
                  Preserved verbatim as description_raw on the returned posting.
        source: Source metadata describing how this job was ingested.

    Returns:
        A fully validated JobPosting.

    Raises:
        ValueError: if the cleaned text is empty, or if title or company
                    cannot be extracted from the description.
        LLMParseError: if the LLM response cannot be parsed or validated.
        anthropic.APIError: on API-level errors.
    """
    cleaned = clean_cv_text(raw_text)
    logger.debug("Parsing job | raw_len=%d | cleaned_len=%d", len(raw_text), len(cleaned))

    if not cleaned:
        raise ValueError(
            "Job description is empty after cleaning. "
            "Please provide a non-empty job description."
        )

    parsed: _JobParseResult = call_llm_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=cleaned,
        response_model=_JobParseResult,
    )

    if not parsed.title:
        raise ValueError(
            "Job title could not be extracted from the description. "
            "Please check that the text is a real job posting."
        )
    if not parsed.company:
        raise ValueError(
            "Company name could not be extracted from the description. "
            "Please check that the text includes the hiring company's name."
        )

    requirements = [
        JobRequirement(
            text=req.text,
            is_required=req.is_required,
            skill_tags=req.skill_tags,
        )
        for req in parsed.requirements
    ]

    posting = JobPosting(
        job_id=generate_id(),
        title=parsed.title,
        company=parsed.company,
        location=parsed.location,
        is_remote=parsed.is_remote,
        description_raw=raw_text,          # verbatim source, never LLM output
        requirements=requirements,
        seniority_level=parsed.seniority_level,
        employment_type=parsed.employment_type,
        source=source,
        normalized_at=utc_now(),
    )

    logger.info(
        "Job parsed | job_id=%s | title=%s | company=%s | requirements=%d",
        posting.job_id,
        posting.title,
        posting.company,
        len(posting.requirements),
    )
    return posting

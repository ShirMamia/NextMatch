"""
Bullet rewriter — per-bullet LLM rewriting with evidence linking.

Each source bullet is rewritten by the LLM to be more relevant to the target job.
Evidence links preserve the verbatim source for downstream validation in Slice 7.

Truthfulness contract:
  - Prompts explicitly prohibit invention (see prompts.py).
  - On LLM parse failure, the original bullet is returned unchanged with confidence=0.0.
    This fallback preserves source grounding: the tailored text equals the original.
  - Callers should treat confidence=0.0 bullets as untailored, not as validated output.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.generation.prompts import (
    BULLET_REWRITE_SYSTEM,
    build_bullet_rewrite_user_prompt,
)
from app.schemas.job import JobPosting
from app.schemas.tailoring import EvidenceLink, TailoredBullet
from app.services.llm_client import LLMParseError, call_llm_structured

logger = logging.getLogger(__name__)


class _BulletRewriteResponse(BaseModel):
    """Internal schema for the LLM bullet rewrite response."""

    model_config = {"extra": "forbid"}

    tailored: str
    confidence: float = Field(ge=0.0, le=1.0)


def _key_requirements(job: JobPosting) -> list[str]:
    """Return up to 5 required requirement texts for prompt context."""
    return [req.text for req in job.requirements if req.is_required][:5]


def rewrite_bullet(
    bullet: str,
    bullet_index: int,
    section_ref: str,
    job: JobPosting,
) -> TailoredBullet:
    """Rewrite a single source bullet targeting the job.

    Makes one LLM call. Falls back to the original bullet on parse failure
    (confidence=0.0) rather than propagating the error, so a single bad
    response does not abort the full section.

    Args:
        bullet: The verbatim source bullet from the candidate profile.
        bullet_index: 0-based index within its section (used in source_section path).
        section_ref: CandidateProfile path to the parent section,
            e.g. "work_experience[0]".
        job: The job posting being targeted.

    Returns:
        A TailoredBullet with evidence linking back to the source.
    """
    user_prompt = build_bullet_rewrite_user_prompt(
        bullet=bullet,
        job_title=job.title,
        company=job.company,
        key_requirements=_key_requirements(job),
    )

    try:
        response = call_llm_structured(
            system_prompt=BULLET_REWRITE_SYSTEM,
            user_prompt=user_prompt,
            response_model=_BulletRewriteResponse,
            max_tokens=256,
        )
        tailored_text = response.tailored.strip() or bullet
        confidence = response.confidence
    except LLMParseError as exc:
        logger.warning(
            "Bullet rewrite failed | section=%s bullet_index=%d — returning original. Error: %s",
            section_ref,
            bullet_index,
            exc,
        )
        tailored_text = bullet
        confidence = 0.0

    return TailoredBullet(
        original=bullet,
        tailored=tailored_text,
        evidence=EvidenceLink(
            source_bullet=bullet,
            source_section=f"{section_ref}.bullets[{bullet_index}]",
            confidence=confidence,
        ),
    )


def rewrite_bullets(
    bullets: list[str],
    section_ref: str,
    job: JobPosting,
) -> list[TailoredBullet]:
    """Rewrite all bullets for one work experience section.

    Processes each bullet independently. A parse failure on one bullet
    returns the original for that bullet only; the rest continue normally.

    Args:
        bullets: The source bullet strings from one WorkExperience entry.
        section_ref: CandidateProfile path to the section, e.g. "work_experience[0]".
        job: The job posting being targeted.

    Returns:
        A list of TailoredBullets in the same order as the input bullets.
    """
    return [
        rewrite_bullet(bullet, i, section_ref, job)
        for i, bullet in enumerate(bullets)
    ]

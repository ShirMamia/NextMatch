"""
Section reorderer — deterministic ordering of work experience entries by job relevance.

This module determines which work experience entries appear first in a tailored resume.
Each entry is scored by how well its title and skills align with the target job.
The ordered list is consumed by resume_tailor.py to build the sections dict in display order.

This module is fully deterministic. No LLM calls.

Scoring model (per work experience entry):
  title_overlap  (weight 0.40) — normalized token overlap with job title
  skill_overlap  (weight 0.40) — fraction of required job skills in exp.skills_used
  recency_bonus  (weight 0.20) — 1.0 if is_current, 0.0 otherwise

Sort is stable (Python's sorted() guarantees this), so entries with equal scores
preserve their original order from the candidate profile.
"""
from __future__ import annotations

import re

from app.schemas.candidate import CandidateProfile, WorkExperience
from app.schemas.job import JobPosting


def _normalize_tokens(s: str) -> set[str]:
    """Tokenize a string into lowercase alphanumeric tokens."""
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _experience_relevance_score(exp: WorkExperience, job: JobPosting) -> float:
    """Score one work experience entry for relevance to the job.

    All factors are bounded [0.0, 1.0]. The weighted sum is therefore bounded
    [0.0, 1.0] as well.
    """
    # Title overlap: how many of the job-title tokens appear in this experience title.
    job_tokens = _normalize_tokens(job.title)
    exp_tokens = _normalize_tokens(exp.title)
    title_overlap = 0.0
    if job_tokens and exp_tokens:
        title_overlap = len(job_tokens & exp_tokens) / len(job_tokens)

    # Required skill overlap: fraction of required job skills present in exp.skills_used.
    required_skills: set[str] = {
        t.lower()
        for req in job.requirements
        if req.is_required
        for t in req.skill_tags
    }
    skill_overlap = 0.0
    if required_skills:
        exp_skills = {s.lower() for s in exp.skills_used}
        skill_overlap = len(required_skills & exp_skills) / len(required_skills)

    # Recency bonus: current role is always the most contextually relevant.
    recency_bonus = 1.0 if exp.is_current else 0.0

    return 0.40 * title_overlap + 0.40 * skill_overlap + 0.20 * recency_bonus


def order_work_experience(
    profile: CandidateProfile,
    job: JobPosting,
) -> list[WorkExperience]:
    """Return the candidate's work experience entries ordered by relevance to the job.

    Uses title token overlap, required skill overlap, and a recency bonus.
    The sort is stable, so entries with identical scores preserve their original order.

    This is the primary entry point used by resume_tailor.py to determine the display
    order of experience sections in the generated TailoredResume.

    Args:
        profile: The candidate's parsed profile.
        job: The job posting to score against.

    Returns:
        Work experience entries sorted descending by relevance score.
        Returns an empty list if profile.work_experience is empty.
    """
    return sorted(
        profile.work_experience,
        key=lambda exp: _experience_relevance_score(exp, job),
        reverse=True,
    )

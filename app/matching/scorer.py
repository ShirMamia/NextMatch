"""
Candidate-job match scorer — deterministic scoring functions.

This module computes CANDIDATE-JOB FIT: how well the candidate's background
matches the requirements of a specific job posting.

It is explicitly NOT search-profile fit (how well a job matches what the user
wants to find). That is implemented in app/discovery/job_ranker.py (Slice 4).

Scoring model:
  skills_score     (weight 0.45) — required + preferred skill coverage
  experience_score (weight 0.30) — work history depth and title relevance
  seniority_score  (weight 0.15) — candidate's apparent seniority vs. job requirement
  education_score  (weight 0.10) — education presence and field relevance

Design principles:
  - Fully deterministic. No LLM calls.
  - Each factor is a small, independently testable function.
  - Scores are bounded [0.0, 1.0].
  - Neutral score (0.5) when a factor has insufficient data.
  - Skills use skill_tags as the primary signal with a raw_text word-boundary fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting, JobRequirement
from app.schemas.match import SkillMatch

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------

WEIGHT_SKILLS = 0.45
WEIGHT_EXPERIENCE = 0.30
WEIGHT_SENIORITY = 0.15
WEIGHT_EDUCATION = 0.10

# ---------------------------------------------------------------------------
# Seniority level map (shared with job_ranker; kept local to avoid coupling)
# ---------------------------------------------------------------------------

_SENIORITY_LEVELS: dict[str, int] = {
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "staff": 4,
    "principal": 5,
}

# Technical field keywords used in education scoring
_TECHNICAL_FIELDS = {
    "computer science", "software engineering", "electrical engineering",
    "computer engineering", "information technology", "information systems",
    "mathematics", "statistics", "physics", "data science", "machine learning",
    "artificial intelligence", "cybersecurity", "network", "computing",
}

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _normalize_tokens(s: str) -> set[str]:
    """Tokenize a string into lowercase alphanumeric tokens.

    Splits on any non-alphanumeric separator so "Senior Backend Engineer"
    → {"senior", "backend", "engineer"}.
    """
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _skill_found(skill: str, candidate_skills: set[str], raw_text: str) -> bool:
    """Return True if skill is in the candidate's skill set or raw CV text.

    Uses skill_set membership as primary signal (structured, fast) and
    word-boundary regex on raw_text as fallback (improves recall for skills
    mentioned in bullets but not listed explicitly).
    """
    if skill.lower() in candidate_skills:
        return True
    pattern = r"(?<![a-zA-Z0-9])" + re.escape(skill) + r"(?![a-zA-Z0-9])"
    return bool(re.search(pattern, raw_text, re.IGNORECASE))


def _candidate_skill_set(profile: CandidateProfile) -> set[str]:
    """Aggregate all skills from profile.skills and work_experience.skills_used."""
    skills: set[str] = {s.lower() for s in profile.skills}
    for exp in profile.work_experience:
        skills.update(s.lower() for s in exp.skills_used)
    return skills


def _collect_unique_skill_tags(
    requirements: list[JobRequirement], *, is_required: bool
) -> list[str]:
    """Collect deduplicated skill tags from required or preferred requirements.

    Preserves original casing for display. Deduplicates by normalized form.
    """
    seen: set[str] = set()
    result: list[str] = []
    for req in requirements:
        if req.is_required is not is_required:
            continue
        for tag in req.skill_tags:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                result.append(tag)
    return result


# ---------------------------------------------------------------------------
# Factor: Skills
# ---------------------------------------------------------------------------

def score_skills(
    profile: CandidateProfile, job: JobPosting
) -> tuple[float, list[SkillMatch]]:
    """Score how well the candidate's skills cover job requirements.

    Computes coverage separately for required and preferred skills, then
    combines them with required skills weighted more heavily.

    Returns:
        (score, skill_matches) where score is in [0.0, 1.0].
        0.5 (neutral) if the job has no skill tags at all.
    """
    required_tags = _collect_unique_skill_tags(job.requirements, is_required=True)
    preferred_tags = _collect_unique_skill_tags(job.requirements, is_required=False)

    if not required_tags and not preferred_tags:
        return 0.5, []

    candidate_skills = _candidate_skill_set(profile)

    # Build the full SkillMatch list (required first, then preferred).
    skill_matches: list[SkillMatch] = []
    for tag in required_tags:
        found = _skill_found(tag, candidate_skills, profile.raw_text)
        skill_matches.append(SkillMatch(skill=tag, found_in_profile=found))
    for tag in preferred_tags:
        found = _skill_found(tag, candidate_skills, profile.raw_text)
        skill_matches.append(SkillMatch(skill=tag, found_in_profile=found))

    # Compute coverage fractions.
    if required_tags:
        matched_req = sum(
            1 for sm in skill_matches[:len(required_tags)] if sm.found_in_profile
        )
        required_coverage = matched_req / len(required_tags)
    else:
        required_coverage = 0.5  # neutral: no required skills specified

    if preferred_tags:
        matched_pref = sum(
            1 for sm in skill_matches[len(required_tags):] if sm.found_in_profile
        )
        preferred_coverage = matched_pref / len(preferred_tags)
    else:
        preferred_coverage = 0.5  # neutral: no preferred skills specified

    # Weighted combination; required skills matter more.
    if required_tags and preferred_tags:
        score = 0.7 * required_coverage + 0.3 * preferred_coverage
    elif required_tags:
        score = required_coverage
    else:
        # Only preferred skills — weight them fully but conservatively.
        score = preferred_coverage * 0.8  # cap at 0.8; can't fully score on preferred only

    return round(min(1.0, max(0.0, score)), 4), skill_matches


# ---------------------------------------------------------------------------
# Factor: Experience
# ---------------------------------------------------------------------------

def score_experience(
    profile: CandidateProfile, job: JobPosting
) -> tuple[float, list[str]]:
    """Score the candidate's experience depth and relevance to the job.

    Uses work experience entry count as a depth proxy and title token overlap
    as a relevance signal. Both are deterministic and conservative.

    Returns:
        (score, notes) where score is in [0.0, 1.0].
        0.0 if the profile has no work experience at all.
        notes contains brief explanations for UI display.
    """
    if not profile.work_experience:
        return 0.0, ["no work experience in candidate profile"]

    # Depth score: count of work experience entries.
    count = len(profile.work_experience)
    if count == 1:
        depth_score = 0.5
    elif count == 2:
        depth_score = 0.7
    else:
        depth_score = 0.9

    # Relevance score: token overlap between experience titles and job title.
    job_tokens = _normalize_tokens(job.title)
    best_overlap = 0.0
    best_title = ""
    for exp in profile.work_experience:
        exp_tokens = _normalize_tokens(exp.title)
        if exp_tokens and job_tokens:
            overlap = len(exp_tokens & job_tokens) / len(job_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best_title = exp.title

    # Relevance score scales with overlap.
    if best_overlap >= 0.75:
        relevance_score = 1.0
    elif best_overlap >= 0.5:
        relevance_score = 0.8
    elif best_overlap >= 0.25:
        relevance_score = 0.6
    elif best_overlap > 0.0:
        relevance_score = 0.4
    else:
        relevance_score = 0.2  # conservative; no overlap found

    score = round(min(1.0, 0.5 * depth_score + 0.5 * relevance_score), 4)

    notes: list[str] = [f"{count} work experience entr{'y' if count == 1 else 'ies'}"]
    if best_title:
        notes.append(f"most relevant title: {best_title}")
    else:
        notes.append("no title overlap with job title")

    return score, notes


# ---------------------------------------------------------------------------
# Factor: Seniority
# ---------------------------------------------------------------------------

def _infer_candidate_seniority(profile: CandidateProfile) -> str | None:
    """Infer seniority level from the candidate's most recent job title.

    Prefers the current role if one is marked. Falls back to the first entry.
    Returns None when no seniority keyword is found.
    """
    current = next((e for e in profile.work_experience if e.is_current), None)
    if current is None and profile.work_experience:
        current = profile.work_experience[0]
    if current is None:
        return None

    title_lower = current.title.lower()
    # Check in descending seniority so "senior" doesn't match inside "principal".
    for level in ("principal", "staff", "lead", "senior", "mid", "junior"):
        if level in title_lower:
            return level
    return None


def score_seniority(
    profile: CandidateProfile, job: JobPosting
) -> tuple[float, list[str]]:
    """Score the alignment between the candidate's seniority and the job's requirement.

    Returns:
        (score, notes) where score is in [0.0, 1.0].
        0.5 (neutral) if job has no seniority requirement or candidate level is unknown.
    """
    if job.seniority_level is None:
        return 0.5, ["job has no seniority requirement specified"]

    job_level = _SENIORITY_LEVELS.get(job.seniority_level.lower())
    if job_level is None:
        return 0.5, [f"unrecognized seniority level in job: {job.seniority_level}"]

    candidate_seniority = _infer_candidate_seniority(profile)
    if candidate_seniority is None:
        return 0.5, ["candidate seniority level could not be inferred from job titles"]

    candidate_level = _SENIORITY_LEVELS.get(candidate_seniority)
    if candidate_level is None:
        return 0.5, [f"unrecognized seniority level inferred: {candidate_seniority}"]

    diff = candidate_level - job_level

    if diff >= 0:
        # At or above required level.
        score = 1.0
        notes = [f"candidate level ({candidate_seniority}) meets or exceeds job requirement ({job.seniority_level})"]
    elif diff == -1:
        # One level below — close but below requirement.
        score = 0.5
        notes = [f"candidate level ({candidate_seniority}) is one step below job requirement ({job.seniority_level})"]
    else:
        # More than one level below.
        score = 0.2
        notes = [f"candidate level ({candidate_seniority}) is below job requirement ({job.seniority_level})"]

    return score, notes


# ---------------------------------------------------------------------------
# Factor: Education
# ---------------------------------------------------------------------------

def score_education(
    profile: CandidateProfile, job: JobPosting
) -> tuple[float, list[str]]:
    """Score education presence and field relevance.

    Since the job schema does not specify education requirements explicitly,
    this factor contributes conservatively based on the candidate's profile.

    Returns:
        (score, notes) where score is in [0.0, 1.0].
        0.5 neutral if no education is present (cannot penalise without requirements context).
    """
    if not profile.education:
        return 0.5, ["no education entries in candidate profile"]

    # Check if any degree is in a technical field.
    is_technical = any(
        any(kw in edu.field.lower() for kw in _TECHNICAL_FIELDS)
        for edu in profile.education
    )

    if is_technical:
        score = 0.9
        fields = ", ".join(edu.field for edu in profile.education)
        notes = [f"technical degree(s): {fields}"]
    else:
        score = 0.7
        fields = ", ".join(edu.field for edu in profile.education)
        notes = [f"education present: {fields}"]

    return score, notes


# ---------------------------------------------------------------------------
# Overall aggregation helper
# ---------------------------------------------------------------------------

def compute_overall_score(
    skills: float,
    experience: float,
    seniority: float,
    education: float,
) -> float:
    """Compute the weighted overall score from component scores."""
    total = (
        WEIGHT_SKILLS * skills
        + WEIGHT_EXPERIENCE * experience
        + WEIGHT_SENIORITY * seniority
        + WEIGHT_EDUCATION * education
    )
    return round(min(1.0, max(0.0, total)), 4)

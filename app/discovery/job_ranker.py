"""
Job ranker — deterministic ranking of job postings against a SearchProfile.

This module implements SEARCH PROFILE FIT only:
how well a discovered job matches what the user says they are looking for.

It is explicitly NOT candidate-job fit (how well the candidate's own
experience and skills match the job). That belongs in Slice 5.

Design principles:
  - Fully deterministic. No LLM calls.
  - Each scoring factor is a small, independently testable function.
  - Scores are bounded [0.0, 1.0].
  - A neutral score (0.5) is returned when a factor has no data to compare.
  - Component scores and reasons are exposed for UI transparency.
  - Excluded keywords apply a multiplicative penalty rather than a hard veto.

Scoring model:
  title_relevance  (weight 0.25)  — job title vs target roles
  required_skills  (weight 0.35)  — profile required skills found in job
  preferred_skills (weight 0.15)  — profile preferred skills found in job
  location_fit     (weight 0.15)  — remote/location preference alignment
  seniority_fit    (weight 0.10)  — job seniority within profile range

  excluded keyword penalty: multiply total by 0.50 if any excluded keyword
  found in job title or raw description.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.job import JobPosting
from app.schemas.search import LocationPreference, SearchProfile

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_WEIGHT_TITLE = 0.25
_WEIGHT_REQUIRED = 0.35
_WEIGHT_PREFERRED = 0.15
_WEIGHT_LOCATION = 0.15
_WEIGHT_SENIORITY = 0.10

_EXCLUDED_PENALTY = 0.50  # multiplied into total score when a keyword hits

# ---------------------------------------------------------------------------
# Seniority level map (higher number = more senior)
# ---------------------------------------------------------------------------

_SENIORITY_LEVELS: dict[str, int] = {
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "staff": 4,
    "principal": 5,
}

# ---------------------------------------------------------------------------
# Result types (dataclasses — ephemeral, never persisted)
# ---------------------------------------------------------------------------

@dataclass
class RankFactor:
    """Score and explanation for a single ranking factor."""

    name: str               # e.g. "title_relevance"
    score: float            # raw component score, 0.0–1.0
    weight: float           # weight applied in aggregation
    reasons: list[str] = field(default_factory=list)


@dataclass
class JobRankResult:
    """Complete ranking result for one job against a search profile."""

    job: JobPosting
    total_score: float              # final weighted score, 0.0–1.0
    factors: list[RankFactor]       # per-factor breakdown
    excluded_keyword_hit: bool      # True if any excluded keyword was found


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def normalize_text(s: str) -> set[str]:
    """Tokenize a string into lowercase alphanumeric tokens.

    Used for title relevance comparison. Splits on any non-alphanumeric
    separator so "Senior Backend Engineer" → {"senior", "backend", "engineer"}.
    """
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _job_skill_set(job: JobPosting) -> set[str]:
    """Collect all skill tags from all job requirements, normalized to lowercase.

    Uses all requirements (required AND preferred) because a skill may appear
    as a 'nice to have' in the job while being required by the profile.
    """
    return {tag.lower() for req in job.requirements for tag in req.skill_tags}


def _skill_in_text(skill: str, text: str) -> bool:
    """Return True if skill appears as a word-boundary match in text (case-insensitive).

    Used as a fallback when a skill is not in job skill_tags but may be mentioned
    in the raw description or title.
    """
    pattern = r"(?<![a-zA-Z0-9])" + re.escape(skill) + r"(?![a-zA-Z0-9])"
    return bool(re.search(pattern, text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------

def score_title_relevance(
    job_title: str, target_roles: list[str]
) -> tuple[float, list[str]]:
    """Score how well the job title matches any target role.

    Uses token overlap: counts what fraction of a target role's tokens appear
    in the job title. Takes the maximum score across all target roles.

    Returns:
        (score, reasons) where score is in [0.0, 1.0].
        0.5 (neutral) if no target roles are specified.
    """
    if not target_roles:
        return 0.5, ["no target roles specified in search profile"]

    job_tokens = normalize_text(job_title)
    best_score = 0.0
    best_role = ""

    for role in target_roles:
        role_tokens = normalize_text(role)
        if not role_tokens:
            continue
        overlap = len(job_tokens & role_tokens) / len(role_tokens)
        if overlap > best_score:
            best_score = overlap
            best_role = role

    score = min(1.0, best_score)
    if score >= 0.8:
        reasons = [f"title closely matches target role: {best_role}"]
    elif score >= 0.5:
        reasons = [f"title partially matches target role: {best_role}"]
    elif score > 0.0:
        reasons = [f"title has some overlap with target role: {best_role}"]
    else:
        reasons = ["title does not match any target role"]

    return score, reasons


def score_required_skills(
    job: JobPosting, required_skills: list[str]
) -> tuple[float, list[str]]:
    """Score the fraction of the profile's required skills found in the job.

    Checks against both job skill_tags (structured) and the raw description
    (word-boundary fallback) for better recall without sacrificing determinism.

    Returns:
        (score, reasons) where score is in [0.0, 1.0].
        0.5 (neutral) if no required skills are specified.
    """
    if not required_skills:
        return 0.5, ["no required skills specified in search profile"]

    job_skills = _job_skill_set(job)
    description_text = job.title + " " + job.description_raw

    matched: list[str] = []
    missing: list[str] = []
    for skill in required_skills:
        if skill.lower() in job_skills or _skill_in_text(skill, description_text):
            matched.append(skill)
        else:
            missing.append(skill)

    score = len(matched) / len(required_skills)
    reasons: list[str] = []
    if matched:
        reasons.append(f"required skills matched: {', '.join(matched)}")
    if missing:
        reasons.append(f"required skills not found: {', '.join(missing)}")

    return score, reasons


def score_preferred_skills(
    job: JobPosting, preferred_skills: list[str]
) -> tuple[float, list[str]]:
    """Score the fraction of the profile's preferred skills found in the job.

    Uses the same matching logic as required skills but with lower weight.

    Returns:
        (score, reasons) where score is in [0.0, 1.0].
        0.5 (neutral) if no preferred skills are specified.
    """
    if not preferred_skills:
        return 0.5, ["no preferred skills specified in search profile"]

    job_skills = _job_skill_set(job)
    description_text = job.title + " " + job.description_raw

    matched = [
        s for s in preferred_skills
        if s.lower() in job_skills or _skill_in_text(s, description_text)
    ]

    score = len(matched) / len(preferred_skills)
    if matched:
        reasons = [f"preferred skills matched: {', '.join(matched)}"]
    else:
        reasons = ["no preferred skills matched"]

    return score, reasons


def score_excluded_keywords(
    job: JobPosting, excluded_keywords: list[str]
) -> tuple[bool, list[str]]:
    """Check whether any excluded keyword appears in the job title or description.

    Returns:
        (excluded, reasons) where excluded=True means a penalty applies.
    """
    if not excluded_keywords:
        return False, []

    searchable = job.title + " " + job.description_raw
    found = [kw for kw in excluded_keywords if _skill_in_text(kw, searchable)]

    if found:
        return True, [f"excluded keyword found: {', '.join(found)}"]
    return False, []


def score_location_fit(
    job: JobPosting, location_pref: LocationPreference
) -> tuple[float, list[str]]:
    """Score how well the job location matches the user's location preferences.

    Remote preference is the primary signal. City/country text matching adds
    a smaller bonus on top.

    Returns:
        (score, reasons) where score is in [0.0, 1.0].
        0.5 (neutral) if no location preference is specified.
    """
    no_preference = (
        location_pref.remote_ok is None
        and location_pref.city is None
        and location_pref.country is None
    )
    if no_preference:
        return 0.5, ["no location preference specified"]

    score = 0.5  # baseline neutral
    reasons: list[str] = []

    # Primary signal: remote preference vs job remote status
    if location_pref.remote_ok is True:
        if job.is_remote is True:
            score = 1.0
            reasons.append("remote work available \u2014 matches remote preference")
        elif job.is_remote is False:
            score = 0.0
            reasons.append("on-site only \u2014 remote work preferred")
        # is_remote=None: keep 0.5, no remote signal
    elif location_pref.remote_ok is False:
        if job.is_remote is False:
            score = 1.0
            reasons.append("on-site \u2014 matches on-site preference")
        elif job.is_remote is True:
            score = 0.3
            reasons.append("remote only \u2014 on-site preferred")

    # Secondary: city/country text match (additive bonus, capped at 1.0)
    if location_pref.city and job.location:
        if location_pref.city.lower() in job.location.lower():
            score = min(1.0, score + 0.2)
            reasons.append(f"city match: {location_pref.city}")
    if location_pref.country and job.location:
        if location_pref.country.lower() in job.location.lower():
            score = min(1.0, score + 0.1)
            reasons.append(f"country match: {location_pref.country}")

    if not reasons:
        reasons.append("location not specified in job posting")

    return round(score, 4), reasons


def score_seniority_fit(
    job_seniority: str | None,
    min_seniority: str | None,
    max_seniority: str | None,
) -> tuple[float, list[str]]:
    """Score how well the job's seniority level fits the profile's seniority range.

    Uses a fixed numeric mapping for recognized levels. Unknown levels return
    0.5 (neutral) rather than failing.

    Returns:
        (score, reasons) where score is in [0.0, 1.0].
        0.5 (neutral) if no seniority preference is specified.
    """
    if min_seniority is None and max_seniority is None:
        return 0.5, ["no seniority preference specified"]

    if job_seniority is None:
        return 0.5, ["job seniority level not specified"]

    job_level = _SENIORITY_LEVELS.get(job_seniority.lower())
    if job_level is None:
        return 0.5, [f"unrecognized seniority level in job: {job_seniority}"]

    min_level = _SENIORITY_LEVELS.get(min_seniority.lower()) if min_seniority else None
    max_level = _SENIORITY_LEVELS.get(max_seniority.lower()) if max_seniority else None

    if min_level is not None and job_level < min_level:
        return 0.0, [
            f"job seniority ({job_seniority}) is below minimum ({min_seniority})"
        ]
    if max_level is not None and job_level > max_level:
        return 0.0, [
            f"job seniority ({job_seniority}) is above maximum ({max_seniority})"
        ]

    return 1.0, [f"seniority match: {job_seniority}"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_search_fit(job: JobPosting, profile: SearchProfile) -> JobRankResult:
    """Compute the search profile fit score for a single job.

    Combines all factor scores into a final weighted total and applies the
    excluded keyword penalty if applicable.

    Args:
        job: The job posting to score.
        profile: The active search profile to rank against.

    Returns:
        A JobRankResult with a total score, per-factor breakdown, and
        excluded keyword flag.
    """
    title_score, title_reasons = score_title_relevance(job.title, profile.target_roles)
    req_score, req_reasons = score_required_skills(job, profile.required_skills)
    pref_score, pref_reasons = score_preferred_skills(job, profile.preferred_skills)
    loc_score, loc_reasons = score_location_fit(job, profile.location_preference)
    sen_score, sen_reasons = score_seniority_fit(
        job.seniority_level, profile.min_seniority, profile.max_seniority
    )
    excluded, excl_reasons = score_excluded_keywords(job, profile.excluded_keywords)

    base = (
        _WEIGHT_TITLE * title_score
        + _WEIGHT_REQUIRED * req_score
        + _WEIGHT_PREFERRED * pref_score
        + _WEIGHT_LOCATION * loc_score
        + _WEIGHT_SENIORITY * sen_score
    )

    total = base * (1.0 - _EXCLUDED_PENALTY) if excluded else base
    total = round(max(0.0, min(1.0, total)), 4)

    factors = [
        RankFactor("title_relevance", title_score, _WEIGHT_TITLE, title_reasons),
        RankFactor("required_skills", req_score, _WEIGHT_REQUIRED, req_reasons),
        RankFactor("preferred_skills", pref_score, _WEIGHT_PREFERRED, pref_reasons),
        RankFactor("location_fit", loc_score, _WEIGHT_LOCATION, loc_reasons),
        RankFactor("seniority_fit", sen_score, _WEIGHT_SENIORITY, sen_reasons),
    ]

    if excluded:
        # Append excluded reasons to the factor that already summarises the job context.
        # They are included in the last factor's reasons for UI visibility.
        factors.append(
            RankFactor("excluded_keywords", 0.0, 0.0, excl_reasons)
        )

    return JobRankResult(
        job=job,
        total_score=total,
        factors=factors,
        excluded_keyword_hit=excluded,
    )


def rank_jobs(
    jobs: list[JobPosting], profile: SearchProfile
) -> list[JobRankResult]:
    """Rank a list of jobs against a search profile, sorted by descending score.

    Args:
        jobs: All ingested job postings.
        profile: The active search profile to rank against.

    Returns:
        A list of JobRankResult sorted from highest to lowest total_score.
        An empty list is returned if jobs is empty.
    """
    if not jobs:
        return []
    results = [compute_search_fit(job, profile) for job in jobs]
    return sorted(results, key=lambda r: r.total_score, reverse=True)

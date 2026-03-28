"""
Gap analyzer — derive gaps, strengths, and recommendations from match data.

Takes the structured outputs of the scorer and produces human-readable lists
that appear in the UI and MatchResult. All logic is deterministic.

Responsibilities:
  - identify_gaps:     what's missing or weak from the candidate's background
  - identify_strengths: what the candidate clearly brings to this job
  - generate_recommendations: actionable next steps derived from gaps

This module does NOT call the LLM and does NOT modify scores.
"""
from __future__ import annotations

from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import SkillMatch


def identify_gaps(
    profile: CandidateProfile,
    job: JobPosting,
    skill_matches: list[SkillMatch],
) -> list[str]:
    """Produce a list of human-readable gap strings for the candidate.

    Priorities:
      1. Missing required skills (highest severity — surface first)
      2. Experience depth concern (no work experience)
      3. Seniority gap (inferred from skill_matches context is not used here;
         seniority gaps are passed in from the scorer notes via matcher.py)

    Args:
        profile: The parsed candidate profile.
        job: The job being matched against.
        skill_matches: The full list produced by scorer.score_skills().

    Returns:
        A list of gap strings, most critical first.
    """
    gaps: list[str] = []

    # Derive the set of required skill tags from the job.
    required_tag_names: set[str] = set()
    for req in job.requirements:
        if req.is_required:
            required_tag_names.update(t.lower() for t in req.skill_tags)

    # Build a lookup: which skills from skill_matches are required?
    matched_skills: dict[str, bool] = {
        sm.skill.lower(): sm.found_in_profile for sm in skill_matches
    }

    missing_required = sorted(
        tag for tag in required_tag_names
        if not matched_skills.get(tag, False)
    )
    for skill in missing_required:
        gaps.append(f"Missing required skill: {skill}")

    if not profile.work_experience:
        gaps.append("No work experience — cannot assess experience alignment")

    return gaps


def identify_strengths(
    profile: CandidateProfile,
    job: JobPosting,
    skill_matches: list[SkillMatch],
) -> list[str]:
    """Produce a list of human-readable strength strings for the candidate.

    Args:
        profile: The parsed candidate profile.
        job: The job being matched against.
        skill_matches: The full list produced by scorer.score_skills().

    Returns:
        A list of strength strings, from most to least impactful.
    """
    strengths: list[str] = []

    required_tag_names: set[str] = set()
    preferred_tag_names: set[str] = set()
    for req in job.requirements:
        if req.is_required:
            required_tag_names.update(t.lower() for t in req.skill_tags)
        else:
            preferred_tag_names.update(t.lower() for t in req.skill_tags)

    matched_required = sorted(
        sm.skill for sm in skill_matches
        if sm.found_in_profile and sm.skill.lower() in required_tag_names
    )
    matched_preferred = sorted(
        sm.skill for sm in skill_matches
        if sm.found_in_profile and sm.skill.lower() in preferred_tag_names
    )

    for skill in matched_required:
        strengths.append(f"Required skill matched: {skill}")
    for skill in matched_preferred:
        strengths.append(f"Preferred skill matched: {skill}")

    if profile.work_experience:
        count = len(profile.work_experience)
        strengths.append(
            f"{count} work experience entr{'y' if count == 1 else 'ies'} on record"
        )

    return strengths


def generate_recommendations(
    gaps: list[str],
    strengths: list[str],
    job: JobPosting,
) -> list[str]:
    """Produce actionable, deterministic recommendations based on gaps and strengths.

    Recommendations are derived from structure, not from LLM generation.
    They are intended to give the candidate clear next steps before applying.

    Args:
        gaps: Output of identify_gaps().
        strengths: Output of identify_strengths().
        job: The job being matched against.

    Returns:
        A list of recommendation strings.
    """
    recommendations: list[str] = []

    missing_required = [
        g.removeprefix("Missing required skill: ")
        for g in gaps
        if g.startswith("Missing required skill:")
    ]

    if missing_required:
        skills_str = ", ".join(missing_required[:3])
        suffix = f" (+{len(missing_required) - 3} more)" if len(missing_required) > 3 else ""
        recommendations.append(
            f"Prioritise demonstrating or developing: {skills_str}{suffix}"
        )

    if any("No work experience" in g for g in gaps):
        recommendations.append(
            "Add concrete work or project experience to strengthen your application"
        )

    if not strengths:
        recommendations.append(
            "Review the job description carefully to identify where your background aligns"
        )
    elif not missing_required:
        recommendations.append(
            "Your skill profile aligns well — focus your resume on the most relevant experience"
        )

    return recommendations

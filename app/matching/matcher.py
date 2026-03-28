"""
Candidate-job matcher — orchestrates scoring into a MatchResult.

This module is the single entry point for Slice 5 candidate-job fit computation.
It calls scorer.py for component scores, assembles ScoreBreakdown, delegates
gap and strength analysis to gap_analyzer.py, and returns a fully populated
MatchResult.

This is CANDIDATE-JOB FIT only. Search-profile fit (Slice 4) is separate.
No LLM calls. All logic is deterministic.
"""
from __future__ import annotations

from app.matching import gap_analyzer, scorer
from app.schemas.candidate import CandidateProfile
from app.schemas.job import JobPosting
from app.schemas.match import MatchResult, ScoreBreakdown
from app.utils.ids import generate_id
from app.utils.time import utc_now


def compute_match(profile: CandidateProfile, job: JobPosting) -> MatchResult:
    """Compute a structured candidate-job fit result.

    Scoring is fully deterministic. All component scores are bounded [0.0, 1.0].
    Neutral scores (0.5) are used when a factor lacks sufficient data.

    Args:
        profile: The parsed candidate profile.
        job: The job posting to match against.

    Returns:
        A fully populated MatchResult with score breakdown, skill matches,
        gaps, strengths, and recommendations.
    """
    # --- Component scoring ---
    skills_score, skill_matches = scorer.score_skills(profile, job)
    experience_score, _exp_notes = scorer.score_experience(profile, job)
    seniority_score, _sen_notes = scorer.score_seniority(profile, job)
    education_score, _edu_notes = scorer.score_education(profile, job)

    overall_score = scorer.compute_overall_score(
        skills=skills_score,
        experience=experience_score,
        seniority=seniority_score,
        education=education_score,
    )

    breakdown = ScoreBreakdown(
        skills_score=skills_score,
        experience_score=experience_score,
        education_score=education_score,
        seniority_score=seniority_score,
        overall_score=overall_score,
    )

    # --- Gap and strength analysis ---
    # Assemble all gaps before generating recommendations so that recommendations
    # are always derived from the complete, final gap list.
    gaps = gap_analyzer.identify_gaps(profile, job, skill_matches)

    # Append seniority gap from scorer notes when the seniority score indicates a
    # meaningful mismatch (below 0.5 means at least one level below the requirement).
    if seniority_score < 0.5 and _sen_notes:
        gaps.append(_sen_notes[0])

    strengths = gap_analyzer.identify_strengths(profile, job, skill_matches)
    recommendations = gap_analyzer.generate_recommendations(gaps, strengths, job)

    return MatchResult(
        match_id=generate_id(),
        candidate_id=profile.candidate_id,
        job_id=job.job_id,
        score_breakdown=breakdown,
        skill_matches=skill_matches,
        gaps=gaps,
        strengths=strengths,
        recommendations=recommendations,
        computed_at=utc_now(),
    )

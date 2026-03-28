"""
Tests for Slice 5 — Candidate-Job Matching (candidate-job fit).

This module tests CANDIDATE-JOB FIT only. It does not test search-profile fit
(Slice 4) or resume generation (Slice 6+).

Covers:
  - _candidate_skill_set: skill aggregation from profile.skills and work_experience
  - score_skills: required coverage, preferred coverage, mixed, empty, description fallback
  - score_experience: depth score, title relevance, no experience
  - _infer_candidate_seniority: keyword detection from titles
  - score_seniority: match, one below, far below, no requirement, unknown level
  - score_education: technical field, non-technical, no education
  - compute_overall_score: weighted aggregation, weight ordering
  - gap_analyzer.identify_gaps: missing required, experience gap
  - gap_analyzer.identify_strengths: matched required, matched preferred, experience
  - gap_analyzer.generate_recommendations: skills-based, experience-based, all-clear
  - compute_match: full MatchResult structure, IDs, score bounds, determinism,
    recommendations consistency with final gaps
  - sparse candidate profile: stable behaviour when all fields are empty or minimal
  - empty-state guards: system behaviour when no candidate profile or no job is present

Empty-state UI behaviour (no profile loaded / no job selected):
  These guards live in tailoring_page.render() which checks session state before
  calling compute_match(). compute_match() itself always requires concrete objects.
  The tests below cover the logic-level equivalent: what happens when the
  candidate profile carries no data at all (truly sparse).
  The session-state guards are thin UI branches verified via manual Streamlit run.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.matching.gap_analyzer import (
    generate_recommendations,
    identify_gaps,
    identify_strengths,
)
from app.matching.matcher import compute_match
from app.matching.scorer import (
    _candidate_skill_set,
    _infer_candidate_seniority,
    compute_overall_score,
    score_education,
    score_experience,
    score_skills,
    score_seniority,
)
from app.schemas.candidate import CandidateProfile, Education, WorkExperience
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.schemas.match import MatchResult, SkillMatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source() -> JobSource:
    return JobSource(
        source_type="manual",
        source_name="manual",
        ingested_at=datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_profile(
    *,
    skills: list[str] | None = None,
    work_experience: list[WorkExperience] | None = None,
    education: list[Education] | None = None,
    raw_text: str = "Senior Backend Engineer with Python and Kafka experience.",
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="cand_test_001",
        name="Test Candidate",
        skills=skills or [],
        work_experience=work_experience or [],
        education=education or [],
        raw_text=raw_text,
        parsed_at=datetime(2026, 3, 26, 9, 0, 0, tzinfo=timezone.utc),
    )


def _make_work_exp(
    title: str = "Senior Backend Engineer",
    company: str = "Acme",
    is_current: bool = True,
    skills_used: list[str] | None = None,
) -> WorkExperience:
    return WorkExperience(
        company=company,
        title=title,
        is_current=is_current,
        skills_used=skills_used or [],
    )


def _make_education(
    field: str = "Computer Science",
    degree: str = "B.Sc.",
    institution: str = "State University",
) -> Education:
    return Education(
        institution=institution,
        degree=degree,
        field=field,
        graduation_year=2020,
    )


def _make_job(
    *,
    title: str = "Senior Backend Engineer",
    company: str = "TechCo",
    requirements: list[JobRequirement] | None = None,
    seniority_level: str | None = "senior",
    description_raw: str = "We need a Senior Backend Engineer.",
) -> JobPosting:
    return JobPosting(
        job_id="job_test_001",
        title=title,
        company=company,
        description_raw=description_raw,
        requirements=requirements or [],
        seniority_level=seniority_level,
        source=_make_source(),
        normalized_at=datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc),
    )


def _req(text: str, *, required: bool, tags: list[str]) -> JobRequirement:
    return JobRequirement(text=text, is_required=required, skill_tags=tags)


# ---------------------------------------------------------------------------
# _candidate_skill_set
# ---------------------------------------------------------------------------

class TestCandidateSkillSet:
    def test_includes_profile_skills(self):
        profile = _make_profile(skills=["Python", "Kafka"])
        result = _candidate_skill_set(profile)
        assert "python" in result
        assert "kafka" in result

    def test_includes_work_experience_skills(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(skills_used=["Docker"])]
        )
        result = _candidate_skill_set(profile)
        assert "docker" in result

    def test_deduplicates_across_sources(self):
        profile = _make_profile(
            skills=["Python"],
            work_experience=[_make_work_exp(skills_used=["Python", "Kafka"])],
        )
        result = _candidate_skill_set(profile)
        assert result == {"python", "kafka"}

    def test_empty_profile_returns_empty_set(self):
        profile = _make_profile()
        assert _candidate_skill_set(profile) == set()


# ---------------------------------------------------------------------------
# score_skills
# ---------------------------------------------------------------------------

class TestScoreSkills:
    def test_all_required_matched(self):
        profile = _make_profile(skills=["Python", "Kafka"])
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Kafka", required=True, tags=["Kafka"]),
        ])
        score, matches = score_skills(profile, job)
        assert score == 1.0
        assert all(sm.found_in_profile for sm in matches)

    def test_no_required_matched(self):
        # raw_text must not mention the job skills to avoid the word-boundary fallback.
        profile = _make_profile(skills=["PHP"], raw_text="A PHP web developer.")
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Kafka", required=True, tags=["Kafka"]),
        ])
        score, matches = score_skills(profile, job)
        assert score == 0.0
        assert not any(sm.found_in_profile for sm in matches)

    def test_partial_required_match(self):
        # raw_text must not mention Kafka to avoid the word-boundary fallback matching it.
        profile = _make_profile(skills=["Python"], raw_text="A Python developer.")
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Kafka", required=True, tags=["Kafka"]),
        ])
        score, _ = score_skills(profile, job)
        assert score == 0.5

    def test_preferred_skills_contribute_less(self):
        """Same required coverage but unmatched preferred → lower score than no preferred at all."""
        profile = _make_profile(skills=["Python"])
        job_no_pref = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
        ])
        job_with_pref = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Docker", required=False, tags=["Docker"]),
        ])
        score_no_pref, _ = score_skills(profile, job_no_pref)
        score_with_pref, _ = score_skills(profile, job_with_pref)
        # Unmatched preferred skill reduces the combined score.
        assert score_with_pref < score_no_pref

    def test_no_requirements_returns_neutral(self):
        profile = _make_profile(skills=["Python"])
        job = _make_job(requirements=[])
        score, matches = score_skills(profile, job)
        assert score == 0.5
        assert matches == []

    def test_description_raw_fallback(self):
        """Skill in raw_text but absent from skill_tags must still be matched."""
        profile = _make_profile(
            skills=[],
            raw_text="Experienced with Python and distributed systems.",
        )
        job = _make_job(requirements=[
            _req("Python experience required", required=True, tags=["Python"]),
        ])
        score, matches = score_skills(profile, job)
        assert score == 1.0
        assert matches[0].found_in_profile is True

    def test_skill_match_list_covers_required_and_preferred(self):
        profile = _make_profile(skills=["Python"])
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Docker", required=False, tags=["Docker"]),
        ])
        _, matches = score_skills(profile, job)
        skills_in_matches = {sm.skill for sm in matches}
        assert "Python" in skills_in_matches
        assert "Docker" in skills_in_matches

    def test_duplicate_tags_across_requirements_deduplicated(self):
        """The same skill tag appearing in two requirements must produce one SkillMatch."""
        profile = _make_profile(skills=["Python"])
        job = _make_job(requirements=[
            _req("Python backend", required=True, tags=["Python"]),
            _req("Python scripting", required=True, tags=["Python"]),
        ])
        _, matches = score_skills(profile, job)
        python_matches = [sm for sm in matches if sm.skill == "Python"]
        assert len(python_matches) == 1


# ---------------------------------------------------------------------------
# score_experience
# ---------------------------------------------------------------------------

class TestScoreExperience:
    def test_no_experience_returns_zero(self):
        profile = _make_profile(work_experience=[])
        score, notes = score_experience(profile, _make_job())
        assert score == 0.0
        assert notes

    def test_one_experience_base_score(self):
        profile = _make_profile(work_experience=[_make_work_exp()])
        score, _ = score_experience(profile, _make_job())
        assert 0.0 < score <= 1.0

    def test_more_experience_scores_higher(self):
        """More work experience entries should produce a higher score, all else equal."""
        profile_1 = _make_profile(work_experience=[_make_work_exp()])
        profile_3 = _make_profile(work_experience=[
            _make_work_exp(is_current=True),
            _make_work_exp(title="Backend Engineer", company="Beta", is_current=False),
            _make_work_exp(title="Junior Developer", company="Gamma", is_current=False),
        ])
        job = _make_job()
        score_1, _ = score_experience(profile_1, job)
        score_3, _ = score_experience(profile_3, job)
        assert score_3 > score_1

    def test_title_overlap_increases_score(self):
        """An experience title matching the job title should score higher than a mismatch."""
        job = _make_job(title="Senior Backend Engineer")
        profile_match = _make_profile(
            work_experience=[_make_work_exp(title="Senior Backend Engineer")]
        )
        profile_mismatch = _make_profile(
            work_experience=[_make_work_exp(title="Marketing Manager")]
        )
        score_match, _ = score_experience(profile_match, job)
        score_mismatch, _ = score_experience(profile_mismatch, job)
        assert score_match > score_mismatch

    def test_score_bounded(self):
        profile = _make_profile(work_experience=[
            _make_work_exp(is_current=True),
            _make_work_exp(title="Backend Developer", company="X", is_current=False),
            _make_work_exp(title="Engineer", company="Y", is_current=False),
        ])
        score, _ = score_experience(profile, _make_job())
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _infer_candidate_seniority
# ---------------------------------------------------------------------------

class TestInferCandidateSeniority:
    def test_senior_in_current_title(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Senior Software Engineer", is_current=True)]
        )
        assert _infer_candidate_seniority(profile) == "senior"

    def test_junior_in_title(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Junior Developer", is_current=True)]
        )
        assert _infer_candidate_seniority(profile) == "junior"

    def test_no_seniority_keyword_returns_none(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Software Engineer", is_current=True)]
        )
        assert _infer_candidate_seniority(profile) is None

    def test_no_experience_returns_none(self):
        assert _infer_candidate_seniority(_make_profile()) is None

    def test_prefers_current_role(self):
        """Current role's seniority should take precedence over past roles."""
        profile = _make_profile(work_experience=[
            _make_work_exp(title="Principal Engineer", is_current=True),
            _make_work_exp(title="Junior Engineer", company="Old", is_current=False),
        ])
        assert _infer_candidate_seniority(profile) == "principal"


# ---------------------------------------------------------------------------
# score_seniority
# ---------------------------------------------------------------------------

class TestScoreSeniority:
    def test_matching_level_returns_one(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Senior Engineer", is_current=True)]
        )
        score, _ = score_seniority(profile, _make_job(seniority_level="senior"))
        assert score == 1.0

    def test_above_required_returns_one(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Principal Engineer", is_current=True)]
        )
        score, _ = score_seniority(profile, _make_job(seniority_level="senior"))
        assert score == 1.0

    def test_one_level_below_returns_partial(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Mid-Level Engineer", is_current=True)]
        )
        score, _ = score_seniority(profile, _make_job(seniority_level="senior"))
        assert 0.0 < score < 1.0

    def test_far_below_returns_low_score(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Junior Developer", is_current=True)]
        )
        score, _ = score_seniority(profile, _make_job(seniority_level="principal"))
        assert score < 0.5

    def test_no_job_seniority_returns_neutral(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Senior Engineer", is_current=True)]
        )
        score, reasons = score_seniority(profile, _make_job(seniority_level=None))
        assert score == 0.5
        assert reasons

    def test_unknown_candidate_level_returns_neutral(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(title="Software Engineer")]
        )
        score, reasons = score_seniority(profile, _make_job(seniority_level="senior"))
        assert score == 0.5
        assert reasons


# ---------------------------------------------------------------------------
# score_education
# ---------------------------------------------------------------------------

class TestScoreEducation:
    def test_technical_degree_returns_high_score(self):
        profile = _make_profile(education=[_make_education(field="Computer Science")])
        score, _ = score_education(profile, _make_job())
        assert score >= 0.85

    def test_non_technical_degree_returns_moderate_score(self):
        profile = _make_profile(education=[_make_education(field="History")])
        score, _ = score_education(profile, _make_job())
        assert 0.5 < score < 0.9

    def test_no_education_returns_neutral(self):
        profile = _make_profile(education=[])
        score, notes = score_education(profile, _make_job())
        assert score == 0.5
        assert notes

    def test_score_bounded(self):
        profile = _make_profile(education=[_make_education()])
        score, _ = score_education(profile, _make_job())
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# compute_overall_score
# ---------------------------------------------------------------------------

class TestComputeOverallScore:
    def test_all_ones_returns_one(self):
        assert compute_overall_score(1.0, 1.0, 1.0, 1.0) == 1.0

    def test_all_zeros_returns_zero(self):
        assert compute_overall_score(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_skills_weighted_most(self):
        """Skills have the highest weight; a skills improvement should outweigh experience."""
        base = compute_overall_score(0.5, 0.5, 0.5, 0.5)
        high_skills = compute_overall_score(1.0, 0.5, 0.5, 0.5)
        high_experience = compute_overall_score(0.5, 1.0, 0.5, 0.5)
        assert (high_skills - base) > (high_experience - base)

    def test_result_bounded(self):
        result = compute_overall_score(0.7, 0.8, 0.6, 0.9)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# gap_analyzer.identify_gaps
# ---------------------------------------------------------------------------

class TestIdentifyGaps:
    def test_missing_required_skill_appears_in_gaps(self):
        # raw_text must not mention Kafka to avoid the word-boundary fallback.
        profile = _make_profile(skills=["Python"], raw_text="A Python developer.")
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Kafka", required=True, tags=["Kafka"]),
        ])
        _, matches = score_skills(profile, job)
        gaps = identify_gaps(profile, job, matches)
        assert any("kafka" in g.lower() for g in gaps)

    def test_matched_required_not_in_gaps(self):
        profile = _make_profile(skills=["Python"])
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        _, matches = score_skills(profile, job)
        gaps = identify_gaps(profile, job, matches)
        assert not any("python" in g.lower() for g in gaps)

    def test_no_experience_appears_in_gaps(self):
        profile = _make_profile(work_experience=[])
        job = _make_job()
        gaps = identify_gaps(profile, job, [])
        assert any("experience" in g.lower() for g in gaps)

    def test_no_gaps_for_matched_skills(self):
        profile = _make_profile(skills=["Python", "Kafka"])
        job = _make_job(requirements=[
            _req("Python", required=True, tags=["Python"]),
            _req("Kafka", required=True, tags=["Kafka"]),
        ])
        _, matches = score_skills(profile, job)
        gaps = identify_gaps(profile, job, matches)
        # No missing required skills — neither Python nor Kafka should appear in gaps.
        assert not any("python" in g.lower() for g in gaps)
        assert not any("kafka" in g.lower() for g in gaps)


# ---------------------------------------------------------------------------
# gap_analyzer.identify_strengths
# ---------------------------------------------------------------------------

class TestIdentifyStrengths:
    def test_matched_required_appears_in_strengths(self):
        profile = _make_profile(skills=["Python"])
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        _, matches = score_skills(profile, job)
        strengths = identify_strengths(profile, job, matches)
        assert any("python" in s.lower() for s in strengths)

    def test_matched_preferred_appears_in_strengths(self):
        profile = _make_profile(skills=["Docker"])
        job = _make_job(requirements=[_req("Docker", required=False, tags=["Docker"])])
        _, matches = score_skills(profile, job)
        strengths = identify_strengths(profile, job, matches)
        assert any("docker" in s.lower() for s in strengths)

    def test_experience_count_appears_in_strengths(self):
        profile = _make_profile(
            work_experience=[_make_work_exp(), _make_work_exp(company="B", is_current=False)]
        )
        job = _make_job()
        strengths = identify_strengths(profile, job, [])
        assert any("experience" in s.lower() for s in strengths)

    def test_no_required_strength_when_nothing_matched(self):
        # raw_text must not mention Python to avoid the word-boundary fallback.
        profile = _make_profile(skills=["PHP"], raw_text="A PHP web developer.")
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        _, matches = score_skills(profile, job)
        strengths = identify_strengths(profile, job, matches)
        # No required skills matched → no "required skill matched" strength.
        required_strengths = [s for s in strengths if "required" in s.lower()]
        assert required_strengths == []


# ---------------------------------------------------------------------------
# gap_analyzer.generate_recommendations
# ---------------------------------------------------------------------------

class TestGenerateRecommendations:
    def test_missing_skills_appear_in_recommendations(self):
        gaps = ["Missing required skill: kafka", "Missing required skill: docker"]
        recommendations = generate_recommendations(gaps, [], _make_job())
        assert any("kafka" in r.lower() or "docker" in r.lower() for r in recommendations)

    def test_no_gaps_produces_positive_recommendation(self):
        recommendations = generate_recommendations([], ["Required skill matched: Python"], _make_job())
        assert recommendations
        assert any("align" in r.lower() or "focus" in r.lower() for r in recommendations)

    def test_no_strengths_produces_review_recommendation(self):
        recommendations = generate_recommendations([], [], _make_job())
        assert any("review" in r.lower() for r in recommendations)

    def test_experience_gap_produces_recommendation(self):
        gaps = ["No work experience — cannot assess experience alignment"]
        recommendations = generate_recommendations(gaps, [], _make_job())
        assert any("experience" in r.lower() or "project" in r.lower() for r in recommendations)


# ---------------------------------------------------------------------------
# compute_match — full MatchResult
# ---------------------------------------------------------------------------

class TestComputeMatch:
    def test_returns_match_result(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert isinstance(result, MatchResult)

    def test_ids_are_set_correctly(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert result.candidate_id == sample_candidate_profile.candidate_id
        assert result.job_id == sample_job_posting.job_id
        assert result.match_id  # non-empty

    def test_overall_score_bounded(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert 0.0 <= result.score_breakdown.overall_score <= 1.0

    def test_all_component_scores_bounded(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        bd = result.score_breakdown
        for score in [bd.skills_score, bd.experience_score, bd.seniority_score, bd.education_score]:
            assert 0.0 <= score <= 1.0

    def test_skill_matches_populated(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert isinstance(result.skill_matches, list)

    def test_gaps_is_list(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert isinstance(result.gaps, list)

    def test_strengths_is_list(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert isinstance(result.strengths, list)

    def test_recommendations_is_list(self, sample_candidate_profile, sample_job_posting):
        result = compute_match(sample_candidate_profile, sample_job_posting)
        assert isinstance(result.recommendations, list)

    def test_match_is_deterministic(self, sample_candidate_profile, sample_job_posting):
        """Running compute_match twice with identical inputs must produce identical scores."""
        result_a = compute_match(sample_candidate_profile, sample_job_posting)
        result_b = compute_match(sample_candidate_profile, sample_job_posting)
        assert result_a.score_breakdown.overall_score == result_b.score_breakdown.overall_score
        assert result_a.score_breakdown.skills_score == result_b.score_breakdown.skills_score
        assert result_a.gaps == result_b.gaps
        assert result_a.strengths == result_b.strengths

    def test_recommendations_consistent_with_gaps(self, sample_candidate_profile, sample_job_posting):
        """Recommendations must reference the same missing skills that appear in final gaps."""
        result = compute_match(sample_candidate_profile, sample_job_posting)
        missing_required_in_gaps = [
            g.removeprefix("Missing required skill: ")
            for g in result.gaps
            if g.startswith("Missing required skill:")
        ]
        if missing_required_in_gaps:
            # At least one of the top-3 missing required skills must appear in recommendations.
            assert any(
                any(skill.lower() in r.lower() for skill in missing_required_in_gaps[:3])
                for r in result.recommendations
            )


# ---------------------------------------------------------------------------
# Sparse candidate profile — stable behaviour when all fields are minimal
# ---------------------------------------------------------------------------

class TestSparseProfile:
    """Verify compute_match is stable when the candidate profile has no meaningful data.

    These tests model the logic-level equivalent of "no candidate data" —
    the most minimal CandidateProfile that is still schema-valid. All scores
    must remain bounded. No exceptions should be raised.
    """

    def test_empty_skills_produces_valid_result(self):
        # raw_text is empty — no fallback signal possible.
        profile = _make_profile(skills=[], work_experience=[], education=[], raw_text="")
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        result = compute_match(profile, job)
        assert 0.0 <= result.score_breakdown.overall_score <= 1.0

    def test_empty_requirements_produces_valid_result(self):
        profile = _make_profile(skills=["Python"], raw_text="")
        job = _make_job(requirements=[])
        result = compute_match(profile, job)
        assert 0.0 <= result.score_breakdown.overall_score <= 1.0

    def test_fully_sparse_profile_does_not_raise(self):
        """A completely empty profile must not raise an exception."""
        profile = _make_profile(raw_text="")
        job = _make_job()
        result = compute_match(profile, job)
        assert isinstance(result, MatchResult)

    def test_sparse_profile_does_not_produce_invalid_scores(self):
        """All component and overall scores must stay in [0.0, 1.0] for a sparse profile."""
        profile = _make_profile(raw_text="")
        job = _make_job(seniority_level=None, requirements=[])
        result = compute_match(profile, job)
        bd = result.score_breakdown
        for score in [
            bd.skills_score, bd.experience_score,
            bd.seniority_score, bd.education_score, bd.overall_score
        ]:
            assert 0.0 <= score <= 1.0

    def test_sparse_profile_returns_gaps_not_strengths(self):
        """A profile with no data should produce gaps and no required-skill strengths."""
        profile = _make_profile(raw_text="")
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        result = compute_match(profile, job)
        required_strengths = [s for s in result.strengths if "required" in s.lower()]
        assert required_strengths == []
        assert any("missing" in g.lower() or "experience" in g.lower() for g in result.gaps)


# ---------------------------------------------------------------------------
# Empty-state guard — no candidate profile / no job
# ---------------------------------------------------------------------------

class TestEmptyStateGuards:
    """Document and test the system boundary when a profile or job is absent.

    compute_match() always requires concrete CandidateProfile and JobPosting
    objects — it does not handle None. The empty-state session-state guards
    live in tailoring_page.render() and are verified via manual Streamlit run.

    These tests confirm the boundary: compute_match is stable for the most
    minimal valid objects, and the system does not fail silently when one
    component carries no domain data.
    """

    def test_job_with_no_requirements_produces_neutral_skills_score(self):
        """When the job specifies no requirements, skills_score must be neutral (0.5)."""
        profile = _make_profile(skills=["Python", "Kafka"], raw_text="A Python developer.")
        job = _make_job(requirements=[])
        result = compute_match(profile, job)
        assert result.score_breakdown.skills_score == 0.5

    def test_profile_with_no_skills_and_no_job_requirements_is_neutral(self):
        """No skills on either side → neutral skills score, valid overall result."""
        profile = _make_profile(skills=[], raw_text="")
        job = _make_job(requirements=[])
        result = compute_match(profile, job)
        assert result.score_breakdown.skills_score == 0.5
        assert isinstance(result, MatchResult)

    def test_missing_required_skills_appear_in_gaps_not_strengths(self):
        """Skills required by the job but absent from the profile must be in gaps, not strengths."""
        profile = _make_profile(skills=[], raw_text="")
        job = _make_job(requirements=[_req("Python", required=True, tags=["Python"])])
        result = compute_match(profile, job)
        gap_skills = [g for g in result.gaps if "python" in g.lower()]
        strength_skills = [s for s in result.strengths if "python" in s.lower()]
        assert gap_skills  # Python is a gap
        assert not strength_skills  # Python is not a strength

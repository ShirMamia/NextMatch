"""
Tests for Slice 4 — Job Ranking (search profile fit).

Covers:
  - normalize_text: tokenisation of job titles and role strings
  - score_title_relevance: full match, partial match, no match, empty target roles
  - score_required_skills: all matched, partial, none, empty list, description fallback
  - score_preferred_skills: matched, unmatched, empty list
  - score_excluded_keywords: keyword found, not found, empty list, word boundary
  - score_location_fit: remote preference variants, city/country bonus, no preference
  - score_seniority_fit: in range, below min, above max, no preference, unknown level
  - compute_search_fit: output structure, weights, excluded penalty applied
  - rank_jobs: sorted descending, empty list, stable with single job, stable ordering under ties
  - no active profile / neutral scoring: all factors return 0.5 when no data
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.discovery.job_ranker import (
    JobRankResult,
    RankFactor,
    compute_search_fit,
    normalize_text,
    rank_jobs,
    score_excluded_keywords,
    score_location_fit,
    score_preferred_skills,
    score_required_skills,
    score_seniority_fit,
    score_title_relevance,
)
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.schemas.search import LocationPreference, SearchProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source() -> JobSource:
    return JobSource(
        source_type="manual",
        source_name="manual",
        ingested_at=datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_job(
    *,
    job_id: str = "job_test_001",
    title: str = "Senior Backend Engineer",
    company: str = "TechCo",
    description_raw: str = "We are looking for a Senior Backend Engineer.",
    requirements: list[JobRequirement] | None = None,
    is_remote: bool | None = True,
    location: str | None = "Remote",
    seniority_level: str | None = "senior",
) -> JobPosting:
    return JobPosting(
        job_id=job_id,
        title=title,
        company=company,
        description_raw=description_raw,
        requirements=requirements or [],
        is_remote=is_remote,
        location=location,
        seniority_level=seniority_level,
        source=_make_source(),
        normalized_at=datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_profile(
    *,
    target_roles: list[str] | None = None,
    required_skills: list[str] | None = None,
    preferred_skills: list[str] | None = None,
    excluded_keywords: list[str] | None = None,
    remote_ok: bool | None = True,
    city: str | None = None,
    country: str | None = None,
    min_seniority: str | None = None,
    max_seniority: str | None = None,
) -> SearchProfile:
    return SearchProfile(
        search_id="search_test_001",
        name="Test Profile",
        target_roles=target_roles or [],
        required_skills=required_skills or [],
        preferred_skills=preferred_skills or [],
        excluded_keywords=excluded_keywords or [],
        location_preference=LocationPreference(
            remote_ok=remote_ok,
            city=city,
            country=country,
        ),
        min_seniority=min_seniority,
        max_seniority=max_seniority,
        created_at=datetime(2026, 3, 26, 9, 0, 0, tzinfo=timezone.utc),
    )


def _empty_search_profile() -> SearchProfile:
    """A profile with no criteria — every scoring factor returns neutral 0.5."""
    return SearchProfile(
        search_id="empty",
        name="Empty",
        target_roles=[],
        required_skills=[],
        preferred_skills=[],
        excluded_keywords=[],
        location_preference=LocationPreference(remote_ok=None),
        min_seniority=None,
        max_seniority=None,
        created_at=datetime(2026, 3, 26, 9, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_basic_tokenisation(self):
        result = normalize_text("Senior Backend Engineer")
        assert result == {"senior", "backend", "engineer"}

    def test_lowercases_input(self):
        assert normalize_text("PYTHON") == {"python"}

    def test_strips_non_alphanumeric(self):
        assert normalize_text("Sr. Backend-Engineer") == {"sr", "backend", "engineer"}

    def test_empty_string(self):
        assert normalize_text("") == set()

    def test_single_token(self):
        assert normalize_text("python") == {"python"}


# ---------------------------------------------------------------------------
# score_title_relevance
# ---------------------------------------------------------------------------

class TestScoreTitleRelevance:
    def test_exact_match_returns_high_score(self):
        score, reasons = score_title_relevance(
            "Senior Backend Engineer", ["Senior Backend Engineer"]
        )
        assert score == 1.0
        assert reasons  # a non-empty explanation must accompany a high score

    def test_partial_match_returns_intermediate_score(self):
        score, _ = score_title_relevance("Senior Engineer", ["Senior Backend Engineer"])
        assert 0.0 < score < 1.0

    def test_no_match_returns_zero(self):
        score, reasons = score_title_relevance("PHP Developer", ["Senior Backend Engineer"])
        assert score == 0.0
        assert reasons  # a non-empty explanation must accompany a zero score

    def test_no_target_roles_returns_neutral(self):
        score, reasons = score_title_relevance("Any Title", [])
        assert score == 0.5
        assert reasons  # must explain why

    def test_best_role_used_when_multiple(self):
        """Score should be the max across all target roles."""
        score_single, _ = score_title_relevance("Staff Engineer", ["Staff Engineer"])
        score_multi, _ = score_title_relevance(
            "Staff Engineer", ["PHP Developer", "Staff Engineer"]
        )
        assert score_multi == score_single

    def test_score_capped_at_one(self):
        score, _ = score_title_relevance(
            "Senior Backend Engineer Python AWS",
            ["Senior Backend Engineer"],
        )
        assert score <= 1.0


# ---------------------------------------------------------------------------
# score_required_skills
# ---------------------------------------------------------------------------

class TestScoreRequiredSkills:
    def test_all_skills_matched_via_tags(self):
        job = _make_job(
            requirements=[
                JobRequirement(text="Python", is_required=True, skill_tags=["Python"]),
                JobRequirement(text="Kafka", is_required=True, skill_tags=["Kafka"]),
            ]
        )
        score, reasons = score_required_skills(job, ["Python", "Kafka"])
        assert score == 1.0
        assert any("matched" in r for r in reasons)

    def test_partial_match_returns_fraction(self):
        job = _make_job(
            requirements=[
                JobRequirement(text="Python", is_required=True, skill_tags=["Python"]),
            ]
        )
        score, _ = score_required_skills(job, ["Python", "Kafka"])
        assert score == 0.5

    def test_no_skills_matched_returns_zero(self):
        job = _make_job(requirements=[
            JobRequirement(text="PHP", is_required=True, skill_tags=["PHP"]),
        ])
        score, reasons = score_required_skills(job, ["Python", "Kafka"])
        assert score == 0.0
        assert any("not found" in r for r in reasons)

    def test_empty_required_skills_returns_neutral(self):
        score, reasons = score_required_skills(_make_job(), [])
        assert score == 0.5
        assert reasons

    def test_description_fallback_matches_skill(self):
        """A skill not in skill_tags but present in description_raw must still match."""
        job = _make_job(
            description_raw="We require strong Python experience.",
            requirements=[],
        )
        score, _ = score_required_skills(job, ["Python"])
        assert score == 1.0

    def test_preferred_skill_tags_also_checked(self):
        """Skill in a preferred requirement's skill_tags must satisfy a required profile skill."""
        job = _make_job(
            requirements=[
                JobRequirement(text="Kafka nice to have", is_required=False, skill_tags=["Kafka"]),
            ]
        )
        score, _ = score_required_skills(job, ["Kafka"])
        assert score == 1.0


# ---------------------------------------------------------------------------
# score_preferred_skills
# ---------------------------------------------------------------------------

class TestScorePreferredSkills:
    def test_all_preferred_matched(self):
        job = _make_job(requirements=[
            JobRequirement(text="Docker", is_required=False, skill_tags=["Docker"]),
        ])
        score, _ = score_preferred_skills(job, ["Docker"])
        assert score == 1.0

    def test_none_matched_returns_zero(self):
        score, reasons = score_preferred_skills(_make_job(), ["Kubernetes"])
        assert score == 0.0
        assert any("no preferred" in r for r in reasons)

    def test_empty_preferred_list_returns_neutral(self):
        score, _ = score_preferred_skills(_make_job(), [])
        assert score == 0.5

    def test_partial_match(self):
        job = _make_job(requirements=[
            JobRequirement(text="Docker", is_required=False, skill_tags=["Docker"]),
        ])
        score, _ = score_preferred_skills(job, ["Docker", "Kubernetes"])
        assert score == 0.5


# ---------------------------------------------------------------------------
# score_excluded_keywords
# ---------------------------------------------------------------------------

class TestScoreExcludedKeywords:
    def test_excluded_keyword_in_title_detected(self):
        job = _make_job(title="PHP Developer", description_raw="Build PHP apps.")
        excluded, reasons = score_excluded_keywords(job, ["PHP"])
        assert excluded is True
        assert any("PHP" in r for r in reasons)

    def test_excluded_keyword_in_description_detected(self):
        job = _make_job(description_raw="Experience with WordPress required.")
        excluded, _ = score_excluded_keywords(job, ["WordPress"])
        assert excluded is True

    def test_no_excluded_keyword_returns_false(self):
        job = _make_job()
        excluded, reasons = score_excluded_keywords(job, ["PHP"])
        assert excluded is False
        assert reasons == []

    def test_empty_excluded_list_returns_false(self):
        excluded, reasons = score_excluded_keywords(_make_job(), [])
        assert excluded is False
        assert reasons == []

    def test_excluded_keyword_is_case_insensitive(self):
        """Keyword match must be case-insensitive."""
        job = _make_job(description_raw="Experience with php required.")
        excluded, _ = score_excluded_keywords(job, ["PHP"])
        assert excluded is True

    def test_word_boundary_prevents_false_positive(self):
        """'PHP' as excluded keyword must not flag a job that only mentions 'PHPUnit'.

        The implementation uses a word-boundary regex with a (?![a-zA-Z0-9]) lookahead,
        so 'PHP' must not match when immediately followed by an alphanumeric character.
        """
        job = _make_job(description_raw="We use PHPUnit for testing.")
        excluded, _ = score_excluded_keywords(job, ["PHP"])
        assert excluded is False


# ---------------------------------------------------------------------------
# score_location_fit
# ---------------------------------------------------------------------------

class TestScoreLocationFit:
    def test_remote_ok_and_job_is_remote_returns_one(self):
        job = _make_job(is_remote=True)
        score, reasons = score_location_fit(job, LocationPreference(remote_ok=True))
        assert score == 1.0
        assert any("remote" in r.lower() for r in reasons)

    def test_remote_ok_but_job_is_onsite_returns_zero(self):
        job = _make_job(is_remote=False)
        score, _ = score_location_fit(job, LocationPreference(remote_ok=True))
        assert score == 0.0

    def test_onsite_preferred_and_job_is_onsite_returns_one(self):
        job = _make_job(is_remote=False)
        score, _ = score_location_fit(job, LocationPreference(remote_ok=False))
        assert score == 1.0

    def test_onsite_preferred_but_job_is_remote_penalised(self):
        job = _make_job(is_remote=True)
        score, _ = score_location_fit(job, LocationPreference(remote_ok=False))
        assert 0.0 < score < 1.0

    def test_no_preference_returns_neutral(self):
        score, reasons = score_location_fit(
            _make_job(), LocationPreference(remote_ok=None, city=None, country=None)
        )
        assert score == 0.5
        assert reasons

    def test_city_match_adds_bonus(self):
        job = _make_job(is_remote=False, location="Tel Aviv, Israel")
        pref = LocationPreference(remote_ok=False, city="Tel Aviv")
        score, reasons = score_location_fit(job, pref)
        assert score > 1.0 - 1e-9  # 1.0 from onsite + city bonus, capped at 1.0
        assert any("city" in r.lower() for r in reasons)

    def test_country_match_adds_bonus(self):
        job = _make_job(is_remote=None, location="Israel")
        pref = LocationPreference(remote_ok=None, country="Israel")
        score, reasons = score_location_fit(job, pref)
        assert score > 0.5  # country bonus applied on top of neutral baseline
        assert any("country" in r.lower() for r in reasons)

    def test_score_bounded_at_one(self):
        job = _make_job(is_remote=True, location="Tel Aviv, Israel")
        pref = LocationPreference(remote_ok=True, city="Tel Aviv", country="Israel")
        score, _ = score_location_fit(job, pref)
        assert score <= 1.0

    def test_remote_unknown_with_remote_ok_preference_returns_neutral(self):
        """job.is_remote=None with remote_ok=True preference → keep 0.5 base."""
        job = _make_job(is_remote=None)
        score, _ = score_location_fit(job, LocationPreference(remote_ok=True))
        assert score == 0.5


# ---------------------------------------------------------------------------
# score_seniority_fit
# ---------------------------------------------------------------------------

class TestScoreSeniorityFit:
    def test_exact_match_within_range(self):
        score, reasons = score_seniority_fit("senior", "senior", "staff")
        assert score == 1.0
        assert any("senior" in r for r in reasons)

    def test_below_minimum_returns_zero(self):
        score, reasons = score_seniority_fit("junior", "senior", None)
        assert score == 0.0
        assert any("below" in r for r in reasons)

    def test_above_maximum_returns_zero(self):
        score, reasons = score_seniority_fit("principal", None, "senior")
        assert score == 0.0
        assert any("above" in r for r in reasons)

    def test_no_preference_returns_neutral(self):
        score, reasons = score_seniority_fit("senior", None, None)
        assert score == 0.5
        assert reasons

    def test_job_seniority_none_returns_neutral(self):
        score, reasons = score_seniority_fit(None, "senior", "staff")
        assert score == 0.5
        assert reasons

    def test_unrecognized_level_returns_neutral(self):
        score, reasons = score_seniority_fit("godmode", "senior", "staff")
        assert score == 0.5
        assert any("unrecognized" in r for r in reasons)

    def test_only_min_seniority_set(self):
        """With only min_seniority, any job at or above min should score 1.0."""
        assert score_seniority_fit("senior", "senior", None)[0] == 1.0
        assert score_seniority_fit("principal", "senior", None)[0] == 1.0

    def test_only_max_seniority_set(self):
        """With only max_seniority, any job at or below max should score 1.0."""
        assert score_seniority_fit("junior", None, "senior")[0] == 1.0
        assert score_seniority_fit("senior", None, "senior")[0] == 1.0


# ---------------------------------------------------------------------------
# compute_search_fit — structure and penalty
# ---------------------------------------------------------------------------

class TestComputeSearchFit:
    def test_returns_job_rank_result(self):
        result = compute_search_fit(_make_job(), _make_profile())
        assert isinstance(result, JobRankResult)

    def test_total_score_bounded(self):
        result = compute_search_fit(_make_job(), _make_profile())
        assert 0.0 <= result.total_score <= 1.0

    def test_factors_list_structure(self):
        result = compute_search_fit(_make_job(), _make_profile())
        assert isinstance(result.factors, list)
        assert len(result.factors) >= 5  # at minimum 5 scoring factors
        for f in result.factors:
            assert isinstance(f, RankFactor)
            assert f.name
            assert 0.0 <= f.score <= 1.0

    def test_excluded_keyword_penalty_applied(self):
        """A job with an excluded keyword must score lower than one without."""
        profile = _make_profile(excluded_keywords=["PHP"])
        job_with_kw = _make_job(description_raw="Must have PHP experience.")
        job_without = _make_job(description_raw="Must have Python experience.")

        result_with = compute_search_fit(job_with_kw, profile)
        result_without = compute_search_fit(job_without, profile)

        assert result_with.excluded_keyword_hit is True
        assert result_without.excluded_keyword_hit is False
        assert result_with.total_score < result_without.total_score

    def test_excluded_keyword_factor_added_when_hit(self):
        """An excluded_keywords RankFactor must appear in factors when penalty applies."""
        profile = _make_profile(excluded_keywords=["PHP"])
        job = _make_job(description_raw="PHP developer needed.")
        result = compute_search_fit(job, profile)
        names = [f.name for f in result.factors]
        assert "excluded_keywords" in names

    def test_no_excluded_hit_flag_is_false(self):
        result = compute_search_fit(_make_job(), _make_profile())
        assert result.excluded_keyword_hit is False

    def test_weights_sum_to_one(self):
        """Non-excluded factors must have weights that sum to 1.0."""
        result = compute_search_fit(_make_job(), _make_profile())
        core_factors = [f for f in result.factors if f.name != "excluded_keywords"]
        total_weight = sum(f.weight for f in core_factors)
        assert abs(total_weight - 1.0) < 1e-9

    def test_job_reference_preserved(self):
        job = _make_job()
        result = compute_search_fit(job, _make_profile())
        assert result.job is job


# ---------------------------------------------------------------------------
# rank_jobs — ordering and edge cases
# ---------------------------------------------------------------------------

class TestRankJobs:
    def test_empty_jobs_returns_empty_list(self):
        results = rank_jobs([], _make_profile())
        assert results == []

    def test_single_job_returned(self):
        results = rank_jobs([_make_job()], _make_profile())
        assert len(results) == 1
        assert isinstance(results[0], JobRankResult)

    def test_sorted_descending_by_score(self):
        """Higher-scoring jobs must appear first."""
        profile = _make_profile(
            target_roles=["Senior Backend Engineer"],
            required_skills=["Python"],
        )
        good_job = _make_job(
            job_id="job_good",
            title="Senior Backend Engineer",
            requirements=[JobRequirement(text="Python", is_required=True, skill_tags=["Python"])],
        )
        poor_job = _make_job(
            job_id="job_poor",
            title="PHP Developer",
            description_raw="Build WordPress themes in PHP.",
        )

        results = rank_jobs([poor_job, good_job], profile)
        assert results[0].job.job_id == "job_good"
        assert results[1].job.job_id == "job_poor"
        assert results[0].total_score >= results[1].total_score

    def test_stable_ordering_for_equal_scores(self):
        """rank_jobs must preserve input order when multiple jobs receive the same score.

        Uses a no-criteria profile so every scoring factor returns neutral 0.5,
        making all jobs tie deterministically. Stable sort (Python's sorted()) must
        keep the original insertion order for tied entries.
        """
        profile = _empty_search_profile()
        job_a = _make_job(job_id="job_a")
        job_b = _make_job(job_id="job_b")
        job_c = _make_job(job_id="job_c")

        results = rank_jobs([job_a, job_b, job_c], profile)

        # All scores must be equal (the tie must be genuine).
        scores = [r.total_score for r in results]
        assert scores[0] == scores[1] == scores[2]

        # Input order must be preserved under the tie.
        output_ids = [r.job.job_id for r in results]
        assert output_ids == ["job_a", "job_b", "job_c"]

    def test_excluded_keyword_job_ranks_last(self):
        """A job with an excluded keyword must rank below one without."""
        profile = _make_profile(excluded_keywords=["PHP"])
        clean_job = _make_job(job_id="job_clean")
        dirty_job = _make_job(
            job_id="job_dirty",
            description_raw="Must know PHP.",
        )

        results = rank_jobs([dirty_job, clean_job], profile)
        scores = {r.job.job_id: r.total_score for r in results}
        assert scores["job_clean"] > scores["job_dirty"]

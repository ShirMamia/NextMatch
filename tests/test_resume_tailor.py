"""
Tests for Slice 6 — Resume tailoring and cover letter generation.

Coverage:
  - section_reorderer: relevance ordering of work experience
  - bullet_rewriter: per-bullet LLM rewriting with evidence and fallback
  - resume_tailor: full TailoredResume assembly including summary and section keys
  - cover_letter_generator: grounded CoverLetterDraft generation

All LLM calls are mocked. These tests verify orchestration logic,
evidence grounding, section key uniqueness, and fallback behavior —
not LLM output quality.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.generation import section_reorderer
from app.generation.bullet_rewriter import rewrite_bullet, rewrite_bullets
from app.generation.cover_letter_generator import generate_cover_letter
from app.generation.resume_tailor import generate_tailored_resume
from app.schemas.candidate import CandidateProfile, Education, WorkExperience
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.schemas.match import MatchResult, ScoreBreakdown, SkillMatch
from app.schemas.tailoring import (
    CoverLetterDraft,
    EvidenceLink,
    GroundedText,
    TailoredBullet,
    TailoredResume,
)
from app.services.llm_client import LLMParseError
from app.utils.time import utc_now


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------

def _make_job_source() -> JobSource:
    return JobSource(source_type="manual", source_name="manual", url=None, ingested_at=utc_now())


def _make_job(
    title: str = "Senior Backend Engineer",
    company: str = "TechCo",
    skill_tags: list[str] | None = None,
) -> JobPosting:
    if skill_tags is None:
        skill_tags = ["Python", "Kafka", "REST"]
    return JobPosting(
        job_id="job_test_001",
        title=title,
        company=company,
        location="Remote",
        is_remote=True,
        description_raw="Senior backend role requiring Python and Kafka.",
        requirements=[
            JobRequirement(
                text="5+ years Python experience",
                is_required=True,
                skill_tags=skill_tags,
            )
        ],
        seniority_level="senior",
        employment_type="full-time",
        source=_make_job_source(),
        normalized_at=utc_now(),
    )


def _make_work_exp(
    title: str = "Software Engineer",
    company: str = "Acme",
    is_current: bool = False,
    skills_used: list[str] | None = None,
    bullets: list[str] | None = None,
    start_date: str = "2020-01",
    end_date: str | None = "2022-12",
) -> WorkExperience:
    # Use `is not None` guards so that an explicit empty list is preserved as-is.
    return WorkExperience(
        company=company,
        title=title,
        start_date=start_date,
        end_date=end_date if not is_current else None,
        is_current=is_current,
        bullets=bullets if bullets is not None else ["Implemented feature X.", "Improved performance by Y%."],
        skills_used=skills_used if skills_used is not None else ["Python"],
    )


def _make_education() -> list[Education]:
    return [
        Education(
            institution="State University",
            degree="B.Sc.",
            field="Computer Science",
            graduation_year=2018,
        )
    ]


def _make_profile(
    work_experience: list[WorkExperience] | None = None,
    skills: list[str] | None = None,
    summary: str = "Experienced backend engineer.",
) -> CandidateProfile:
    # Use `is not None` guard so that an explicit empty list is preserved as-is.
    return CandidateProfile(
        candidate_id="cand_test_001",
        name="Jane Smith",
        email="jane@example.com",
        location="Remote",
        summary=summary,
        skills=skills if skills is not None else ["Python", "Kafka", "REST"],
        work_experience=work_experience if work_experience is not None else [_make_work_exp()],
        education=_make_education(),
        languages=["English"],
        raw_text="Jane Smith. Experienced backend engineer.",
        parsed_at=utc_now(),
    )


def _make_match_result(
    profile: CandidateProfile | None = None,
    job: JobPosting | None = None,
) -> MatchResult:
    profile = profile or _make_profile()
    job = job or _make_job()
    return MatchResult(
        match_id="match_test_001",
        candidate_id=profile.candidate_id,
        job_id=job.job_id,
        score_breakdown=ScoreBreakdown(
            skills_score=0.8,
            experience_score=0.7,
            education_score=0.6,
            seniority_score=0.9,
            overall_score=0.75,
        ),
        skill_matches=[
            SkillMatch(
                skill="Python",
                found_in_profile=True,
                evidence_snippets=["Python listed in skills"],
            ),
        ],
        strengths=["Strong Python background", "Kafka experience"],
        gaps=["No Kubernetes experience"],
        recommendations=["Highlight distributed systems work"],
        computed_at=utc_now(),
    )


def _make_tailored_bullet(
    original: str = "Did something.",
    source_section: str = "work_experience[0].bullets[0]",
) -> TailoredBullet:
    return TailoredBullet(
        original=original,
        tailored=original,
        evidence=EvidenceLink(
            source_bullet=original,
            source_section=source_section,
            confidence=0.0,
        ),
    )


def _mock_summary_response(summary: str = "Targeted professional summary.") -> MagicMock:
    resp = MagicMock()
    resp.summary = summary
    resp.confidence = 0.8
    resp.evidence_indices = [1]
    return resp


def _mock_cover_letter_response(body: str = "Dear Hiring Manager, ...") -> MagicMock:
    resp = MagicMock()
    resp.body = body
    resp.evidence_indices = [1]
    return resp


# ---------------------------------------------------------------------------
# section_reorderer tests
# ---------------------------------------------------------------------------

class TestSectionReorderer:
    """Tests for deterministic work experience ordering by job relevance."""

    def test_highly_relevant_experience_ranks_first(self) -> None:
        """An entry whose title and skills closely match the job should rank first."""
        relevant = _make_work_exp(
            title="Senior Backend Engineer",
            skills_used=["Python", "Kafka", "REST"],
            is_current=True,
        )
        irrelevant = _make_work_exp(
            title="Marketing Coordinator",
            skills_used=["Excel", "Salesforce"],
            is_current=False,
        )
        profile = _make_profile(work_experience=[irrelevant, relevant])
        job = _make_job(title="Senior Backend Engineer", skill_tags=["Python", "Kafka", "REST"])

        ordered = section_reorderer.order_work_experience(profile, job)

        assert ordered[0] is relevant
        assert ordered[1] is irrelevant

    def test_preserves_all_entries(self) -> None:
        """Reordering must not drop any work experience entries."""
        exps = [_make_work_exp(company=f"Company{i}") for i in range(4)]
        profile = _make_profile(work_experience=exps)
        job = _make_job()

        ordered = section_reorderer.order_work_experience(profile, job)

        assert len(ordered) == 4
        assert set(id(e) for e in ordered) == set(id(e) for e in exps)

    def test_empty_experience_returns_empty(self) -> None:
        profile = _make_profile(work_experience=[])
        ordered = section_reorderer.order_work_experience(profile, _make_job())
        assert ordered == []

    def test_single_entry_returns_itself(self) -> None:
        exp = _make_work_exp()
        profile = _make_profile(work_experience=[exp])
        ordered = section_reorderer.order_work_experience(profile, _make_job())
        assert len(ordered) == 1
        assert ordered[0] is exp

    def test_recency_bonus_for_current_role(self) -> None:
        """When skills and title are similar, the current role should rank first."""
        current = _make_work_exp(
            title="Software Engineer",
            skills_used=["Python"],
            is_current=True,
            end_date=None,
        )
        older = _make_work_exp(
            title="Software Engineer",
            skills_used=["Python"],
            is_current=False,
            start_date="2015-01",
            end_date="2017-12",
        )
        profile = _make_profile(work_experience=[older, current])
        job = _make_job(title="Software Engineer", skill_tags=["Python"])

        ordered = section_reorderer.order_work_experience(profile, job)

        assert ordered[0] is current


# ---------------------------------------------------------------------------
# bullet_rewriter tests
# ---------------------------------------------------------------------------

class TestBulletRewriter:
    """Tests for per-bullet LLM rewriting with evidence grounding."""

    def test_rewrite_bullet_returns_tailored_bullet(self) -> None:
        source = "Built REST APIs in FastAPI."
        mock_response = MagicMock()
        mock_response.tailored = "Engineered high-performance REST APIs using FastAPI."
        mock_response.confidence = 0.8

        with patch("app.generation.bullet_rewriter.call_llm_structured", return_value=mock_response):
            result = rewrite_bullet(
                bullet=source,
                bullet_index=0,
                section_ref="work_experience[0]",
                job=_make_job(),
            )

        assert isinstance(result, TailoredBullet)
        assert result.original == source
        assert result.tailored == "Engineered high-performance REST APIs using FastAPI."
        assert result.evidence.confidence == 0.8
        assert result.evidence.source_bullet == source
        assert result.evidence.source_section == "work_experience[0].bullets[0]"

    def test_evidence_section_path_uses_bullet_index(self) -> None:
        """The evidence source_section path must embed the bullet index."""
        source = "Did something important."
        mock_response = MagicMock()
        mock_response.tailored = source
        mock_response.confidence = 0.0

        with patch("app.generation.bullet_rewriter.call_llm_structured", return_value=mock_response):
            result = rewrite_bullet(
                bullet=source,
                bullet_index=2,
                section_ref="work_experience[1]",
                job=_make_job(),
            )

        assert result.evidence.source_section == "work_experience[1].bullets[2]"

    def test_fallback_to_original_on_llm_parse_error(self) -> None:
        """On LLMParseError, the bullet is returned unchanged with confidence 0.0."""
        source = "Original bullet text."
        with patch(
            "app.generation.bullet_rewriter.call_llm_structured",
            side_effect=LLMParseError("bad json", ""),
        ):
            result = rewrite_bullet(
                bullet=source,
                bullet_index=0,
                section_ref="work_experience[0]",
                job=_make_job(),
            )

        assert result.tailored == source
        assert result.original == source
        assert result.evidence.confidence == 0.0

    def test_rewrite_bullets_processes_all(self) -> None:
        """rewrite_bullets must return one TailoredBullet per input bullet."""
        bullets = ["Bullet A.", "Bullet B.", "Bullet C."]
        mock_response = MagicMock()
        mock_response.tailored = "Tailored."
        mock_response.confidence = 0.7

        with patch("app.generation.bullet_rewriter.call_llm_structured", return_value=mock_response):
            results = rewrite_bullets(
                bullets=bullets,
                section_ref="work_experience[0]",
                job=_make_job(),
            )

        assert len(results) == 3
        for i, (tb, orig) in enumerate(zip(results, bullets)):
            assert tb.original == orig
            assert tb.evidence.source_section == f"work_experience[0].bullets[{i}]"

    def test_rewrite_bullets_empty_input(self) -> None:
        results = rewrite_bullets(bullets=[], section_ref="work_experience[0]", job=_make_job())
        assert results == []


# ---------------------------------------------------------------------------
# generate_tailored_resume tests
# ---------------------------------------------------------------------------

class TestGenerateTailoredResume:
    """Tests for full TailoredResume assembly."""

    def _run_generate(
        self,
        profile: CandidateProfile,
        job: JobPosting | None = None,
        match_result: MatchResult | None = None,
        summary_response: MagicMock | None = None,
    ) -> TailoredResume:
        job = job or _make_job()
        match_result = match_result or _make_match_result(profile=profile, job=job)
        summary_resp = summary_response or _mock_summary_response()

        with (
            patch("app.generation.resume_tailor.bullet_rewriter.rewrite_bullets") as mock_bw,
            patch("app.generation.resume_tailor.call_llm_structured", return_value=summary_resp),
        ):
            mock_bw.side_effect = lambda bullets, section_ref, job: [
                _make_tailored_bullet(original=b, source_section=f"{section_ref}.bullets[{i}]")
                for i, b in enumerate(bullets)
            ]
            return generate_tailored_resume(profile, job, match_result)

    def test_returns_tailored_resume_schema(self) -> None:
        profile = _make_profile()
        result = self._run_generate(profile)
        assert isinstance(result, TailoredResume)

    def test_resume_ids_linked_correctly(self) -> None:
        profile = _make_profile()
        job = _make_job()
        match_result = _make_match_result(profile=profile, job=job)
        result = self._run_generate(profile, job=job, match_result=match_result)
        assert result.candidate_id == profile.candidate_id
        assert result.job_id == job.job_id
        assert result.match_id == match_result.match_id

    def test_sections_contain_tailored_bullets(self) -> None:
        exp = _make_work_exp(bullets=["Bullet one.", "Bullet two."])
        profile = _make_profile(work_experience=[exp])
        result = self._run_generate(profile)
        assert len(result.sections) == 1
        bullets = list(result.sections.values())[0]
        assert len(bullets) == 2

    def test_section_key_format(self) -> None:
        """Section keys must follow 'work_experience[N] — Company — Title' format."""
        exp = _make_work_exp(company="Acme", title="Software Engineer")
        profile = _make_profile(work_experience=[exp])
        result = self._run_generate(profile)
        keys = list(result.sections.keys())
        assert len(keys) == 1
        assert keys[0].startswith("work_experience[")
        assert "Acme" in keys[0]
        assert "Software Engineer" in keys[0]

    def test_section_keys_are_collision_safe(self) -> None:
        """Two work experience entries with identical company AND title must
        produce two distinct, index-prefixed section keys.

        This verifies that the section key format 'work_experience[N] — Company — Title'
        prevents dict key collision when company and title are the same across entries.
        Without the index prefix, the second entry would silently overwrite the first.
        """
        # Both entries share the exact same company and title — a real collision scenario.
        exp_0 = _make_work_exp(
            title="Software Engineer",
            company="Acme",
            is_current=True,
            bullets=["First role bullet."],
            start_date="2022-01",
            end_date=None,
        )
        exp_1 = _make_work_exp(
            title="Software Engineer",
            company="Acme",
            is_current=False,
            bullets=["Second role bullet."],
            start_date="2019-01",
            end_date="2021-12",
        )
        profile = _make_profile(work_experience=[exp_0, exp_1])
        job = _make_job()
        match_result = _make_match_result(profile=profile, job=job)

        with (
            patch("app.generation.resume_tailor.bullet_rewriter.rewrite_bullets") as mock_bw,
            patch(
                "app.generation.resume_tailor.call_llm_structured",
                return_value=_mock_summary_response(),
            ),
        ):
            mock_bw.side_effect = lambda bullets, section_ref, job: [
                _make_tailored_bullet(original=b, source_section=f"{section_ref}.bullets[{i}]")
                for i, b in enumerate(bullets)
            ]
            result = generate_tailored_resume(profile, job, match_result)

        # 1. Both sections are present — neither was dropped.
        assert len(result.sections) == 2, (
            f"Expected 2 sections but got {len(result.sections)}: {list(result.sections.keys())}"
        )

        keys = list(result.sections.keys())

        # 2. All keys are unique — neither entry overwrote the other.
        assert len(keys) == len(set(keys)), (
            f"Duplicate section keys found: {keys}"
        )

        # 3. All keys carry the index prefix, proving the collision-safe format is used.
        for key in keys:
            assert key.startswith("work_experience["), (
                f"Section key is missing the index prefix: {key!r}"
            )

        # 4. The two keys differ — confirm distinct entries are represented.
        assert keys[0] != keys[1]

    def test_summary_is_grounded_text(self) -> None:
        profile = _make_profile(summary="Experienced engineer.")
        result = self._run_generate(profile)
        assert isinstance(result.summary, GroundedText)
        assert result.summary.text  # non-empty when profile has summary

    def test_summary_empty_when_no_profile_summary(self) -> None:
        """When the profile has no summary, TailoredResume.summary.text must be empty."""
        profile = _make_profile(summary="")
        result = self._run_generate(profile)
        assert result.summary.text == ""

    def test_skips_experience_entries_with_no_bullets(self) -> None:
        exp_with = _make_work_exp(bullets=["Has content."])
        exp_without = _make_work_exp(company="Empty Corp", bullets=[])
        profile = _make_profile(work_experience=[exp_with, exp_without])
        result = self._run_generate(profile)
        # Only the entry with bullets should appear in sections.
        assert all("Empty Corp" not in k for k in result.sections), (
            f"Empty-bullet entry unexpectedly produced a section: {list(result.sections.keys())}"
        )

    def test_resume_is_unapproved_by_default(self) -> None:
        profile = _make_profile()
        result = self._run_generate(profile)
        assert result.approved is False
        assert result.approved_at is None


# ---------------------------------------------------------------------------
# generate_cover_letter tests
# ---------------------------------------------------------------------------

class TestGenerateCoverLetter:
    """Tests for grounded cover letter draft generation."""

    def _run_generate(
        self,
        profile: CandidateProfile,
        job: JobPosting | None = None,
        match_result: MatchResult | None = None,
        cover_letter_response: MagicMock | None = None,
    ) -> CoverLetterDraft:
        job = job or _make_job()
        match_result = match_result or _make_match_result(profile=profile, job=job)
        cl_resp = cover_letter_response or _mock_cover_letter_response()

        with patch(
            "app.generation.cover_letter_generator.call_llm_structured",
            return_value=cl_resp,
        ):
            return generate_cover_letter(profile, job, match_result)

    def test_returns_cover_letter_draft_schema(self) -> None:
        profile = _make_profile()
        result = self._run_generate(profile)
        assert isinstance(result, CoverLetterDraft)

    def test_ids_linked_correctly(self) -> None:
        profile = _make_profile()
        job = _make_job()
        match_result = _make_match_result(profile=profile, job=job)
        result = self._run_generate(profile, job=job, match_result=match_result)
        assert result.candidate_id == profile.candidate_id
        assert result.job_id == job.job_id
        assert result.match_id == match_result.match_id

    def test_body_is_non_empty(self) -> None:
        profile = _make_profile()
        cl_resp = _mock_cover_letter_response(body="  Dear Hiring Manager, here is my letter.  ")
        result = self._run_generate(profile, cover_letter_response=cl_resp)
        assert result.body.strip()

    def test_evidence_links_are_present(self) -> None:
        """CoverLetterDraft must include at least one evidence link."""
        profile = _make_profile()
        result = self._run_generate(profile)
        assert len(result.evidence_links) >= 1

    def test_evidence_links_are_profile_native(self) -> None:
        """Evidence link source sections must be CandidateProfile paths, not match_result fields."""
        profile = _make_profile()
        result = self._run_generate(profile)
        for ev in result.evidence_links:
            assert "strength" not in ev.source_section.lower(), (
                f"Evidence link references a match_result field, not a profile path: {ev.source_section!r}"
            )

    def test_raises_value_error_on_empty_profile(self) -> None:
        """generate_cover_letter must raise ValueError if the profile has no grounding material."""
        profile = CandidateProfile(
            candidate_id="cand_empty",
            name="Empty Person",
            email=None,
            location=None,
            summary="",
            skills=[],
            work_experience=[],
            education=[],
            languages=[],
            raw_text="",
            parsed_at=utc_now(),
        )
        with pytest.raises(ValueError, match="empty profile"):
            generate_cover_letter(profile, _make_job(), _make_match_result(profile=profile))

    def test_llm_parse_error_propagates(self) -> None:
        """LLMParseError must propagate without fallback for cover letters."""
        profile = _make_profile()
        with (
            patch(
                "app.generation.cover_letter_generator.call_llm_structured",
                side_effect=LLMParseError("bad json", ""),
            ),
            pytest.raises(LLMParseError),
        ):
            generate_cover_letter(profile, _make_job(), _make_match_result(profile=profile))

    def test_fallback_evidence_when_no_valid_indices(self) -> None:
        """When the model returns no valid evidence indices, fall back to the first source."""
        profile = _make_profile()
        cl_resp = _mock_cover_letter_response()
        cl_resp.evidence_indices = []  # model returned no indices

        result = self._run_generate(profile, cover_letter_response=cl_resp)

        assert len(result.evidence_links) == 1
        # Fallback links to the first available source (profile.summary).
        assert result.evidence_links[0].source_section == "profile.summary"

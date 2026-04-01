"""
Tests for Slice 7 — Validation.

Coverage:
  - claim_checker: _extract_numbers() and check_bullet() deterministic heuristics
  - validator: validate_resume() and validate_cover_letter() orchestration
  - ValidationReport schema: passed computed correctly from flags

All tests are deterministic. No LLM calls.
"""
from __future__ import annotations

import pytest

from app.schemas.tailoring import (
    CoverLetterDraft,
    EvidenceLink,
    GroundedText,
    TailoredBullet,
    TailoredResume,
)
from app.schemas.validation import (
    FlagSeverity,
    FlagType,
    ValidationFlag,
    ValidationReport,
)
from app.utils.time import utc_now
from app.utils.ids import generate_id


# ---------------------------------------------------------------------------
# Shared factory helpers
# ---------------------------------------------------------------------------

def _ev(
    source_bullet: str = "Source bullet text.",
    source_section: str = "work_experience[0].bullets[0]",
    confidence: float = 0.8,
) -> EvidenceLink:
    return EvidenceLink(
        source_bullet=source_bullet,
        source_section=source_section,
        confidence=confidence,
    )


def _bullet(
    original: str = "Original bullet.",
    tailored: str = "Tailored bullet.",
    evidence: EvidenceLink | None = None,
) -> TailoredBullet:
    return TailoredBullet(
        original=original,
        tailored=tailored,
        evidence=evidence or _ev(source_bullet=original),
    )


def _grounded(
    text: str = "Summary text.",
    evidence_links: list[EvidenceLink] | None = None,
) -> GroundedText:
    return GroundedText(
        text=text,
        evidence_links=evidence_links if evidence_links is not None else [_ev()],
    )


def _resume(
    sections: dict[str, list[TailoredBullet]] | None = None,
    summary: GroundedText | None = None,
) -> TailoredResume:
    # Use `is not None` guards so explicit empty values (e.g. sections={}) are preserved.
    return TailoredResume(
        resume_id="resume_001",
        candidate_id="cand_001",
        job_id="job_001",
        match_id="match_001",
        summary=summary if summary is not None else _grounded(),
        sections=sections if sections is not None else {
            "work_experience[0] — Acme — Engineer": [_bullet()]
        },
    )


def _cover_letter(
    body: str = "Dear Hiring Manager, I am writing to apply...",
    evidence_links: list[EvidenceLink] | None = None,
) -> CoverLetterDraft:
    return CoverLetterDraft(
        draft_id="draft_001",
        candidate_id="cand_001",
        job_id="job_001",
        match_id="match_001",
        body=body,
        evidence_links=evidence_links if evidence_links is not None else [_ev()],
    )


def _flag(
    severity: FlagSeverity = FlagSeverity.WARNING,
    flag_type: FlagType = FlagType.UNSUPPORTED_CLAIM,
    message: str = "Test flag.",
    location: str = "test.location",
) -> ValidationFlag:
    return ValidationFlag(
        flag_id=generate_id(),
        severity=severity,
        flag_type=flag_type,
        message=message,
        location=location,
    )


# ---------------------------------------------------------------------------
# _extract_numbers() tests — imported directly to verify regex correctness
# ---------------------------------------------------------------------------

class TestExtractNumbers:
    """
    Direct tests for _extract_numbers() to verify number/percentage detection.

    These tests confirm that the regex correctly captures integers, decimals,
    percentages, and decimal percentages — all core to the unsupported-metric check.
    """

    def setup_method(self) -> None:
        from app.validation.claim_checker import _extract_numbers
        self._extract = _extract_numbers

    def test_plain_integer(self) -> None:
        """An integer like '20' must be extracted."""
        result = self._extract("Reduced latency by 20 milliseconds.")
        assert "20" in result

    def test_decimal_number(self) -> None:
        """A decimal like '20.5' must be extracted."""
        result = self._extract("Improved throughput by 20.5 times.")
        assert "20.5" in result

    def test_percentage(self) -> None:
        """A percentage like '20%' must be extracted (not just '20')."""
        result = self._extract("Reduced costs by 20%.")
        assert "20%" in result

    def test_decimal_percentage(self) -> None:
        """A decimal percentage like '20.5%' must be extracted."""
        result = self._extract("Improved efficiency by 20.5%.")
        assert "20.5%" in result

    def test_multiple_numbers(self) -> None:
        """Multiple numbers in the same text are all extracted."""
        result = self._extract("Reduced latency by 40% and cost by 20%.")
        assert "40%" in result
        assert "20%" in result

    def test_no_numbers_returns_empty(self) -> None:
        """Text with no numbers returns an empty set."""
        result = self._extract("Built REST APIs in Python.")
        assert result == set()


# ---------------------------------------------------------------------------
# check_bullet() tests
# ---------------------------------------------------------------------------

class TestCheckBullet:
    """Tests for the per-bullet deterministic claim checker."""

    def setup_method(self) -> None:
        from app.validation.claim_checker import check_bullet
        self._check = check_bullet

    def test_well_grounded_bullet_no_flags(self) -> None:
        """A tailored bullet closely derived from its source should produce no flags."""
        source = "Built REST APIs using Python and FastAPI to serve internal clients."
        tailored = "Developed REST APIs using Python and FastAPI for internal client use."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        # Must not produce number or seniority flags.
        assert all(
            "%" not in f.message and "seniority" not in f.message.lower()
            for f in flags
        )

    def test_unsupported_percentage_produces_warning(self) -> None:
        """An unsupported percentage in the tailored text must produce an UNSUPPORTED_CLAIM warning."""
        source = "Improved system performance significantly."
        tailored = "Improved system performance by 40%."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        unsupported_claim_flags = [f for f in flags if f.flag_type == FlagType.UNSUPPORTED_CLAIM]
        assert any("40%" in f.message for f in unsupported_claim_flags), (
            f"Expected UNSUPPORTED_CLAIM flag for '40%', got: {[f.message for f in flags]}"
        )

    def test_unsupported_integer_produces_warning(self) -> None:
        """An unsupported integer in the tailored text must produce an UNSUPPORTED_CLAIM warning."""
        source = "Mentored junior engineers on the team."
        tailored = "Mentored 5 junior engineers on the team."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        unsupported = [f for f in flags if f.flag_type == FlagType.UNSUPPORTED_CLAIM]
        assert any("5" in f.message for f in unsupported), (
            f"Expected UNSUPPORTED_CLAIM flag for '5', got: {[f.message for f in flags]}"
        )

    def test_number_present_in_source_not_flagged(self) -> None:
        """A number that appears in both tailored and source must not be flagged."""
        source = "Led a team of 5 engineers and reduced latency by 40%."
        tailored = "Managed a team of 5 engineers, achieving a 40% latency reduction."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        number_flags = [
            f for f in flags
            if "40%" in f.message or ("'5'" in f.message and "metric" in f.message.lower())
        ]
        assert not number_flags, f"Unexpected number flags: {[f.message for f in number_flags]}"

    def test_unsupported_seniority_term_produces_warning(self) -> None:
        """'Led' in tailored text absent from source must produce an UNSUPPORTED_CLAIM warning."""
        source = "Contributed to the migration of the monolithic service."
        tailored = "Led the migration of the monolithic service to microservices."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        seniority_flags = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "led" in f.message.lower()
        ]
        assert seniority_flags, (
            f"Expected seniority flag for 'led', got: {[f.message for f in flags]}"
        )

    def test_seniority_term_present_in_source_not_flagged(self) -> None:
        """'Led' in tailored text that also appears in the source must not produce a seniority flag."""
        source = "Led a cross-functional team to deliver the project on schedule."
        tailored = "Led a cross-functional team delivering the project on time."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        seniority_flags = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "led" in f.message.lower()
        ]
        assert not seniority_flags, (
            f"Unexpected seniority flag: {[f.message for f in seniority_flags]}"
        )

    def test_unsupported_tech_term_produces_warning(self) -> None:
        """A technology name in tailored text absent from the source produces a warning."""
        source = "Built data pipelines using Python scripts."
        tailored = "Built data pipelines using Python and Kubernetes orchestration."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        tech_flags = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "Kubernetes" in f.message
        ]
        assert tech_flags, (
            f"Expected UNSUPPORTED_CLAIM flag for 'Kubernetes', got: {[f.message for f in flags]}"
        )

    def test_tech_term_in_source_not_flagged(self) -> None:
        """A technology present in both tailored and source must not produce a tech flag."""
        source = "Deployed services using Kubernetes on AWS."
        tailored = "Deployed production services using Kubernetes and AWS infrastructure."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        tech_flags = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "Kubernetes" in f.message
        ]
        assert not tech_flags, f"Unexpected Kubernetes flag: {[f.message for f in tech_flags]}"

    def test_verb_paraphrase_does_not_trigger_tech_flag(self) -> None:
        """Replacing a sentence-starting verb (e.g. 'Built' → 'Developed') must NOT produce
        an UNSUPPORTED_CLAIM flag for the verb — common resume verbs are not technology names."""
        source = "Built high-performance REST APIs serving internal clients."
        tailored = "Developed high-performance REST APIs serving internal clients."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        # "Developed" is a common sentence-starting verb, not a tech name.
        tech_flags_for_developed = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "Developed" in f.message
        ]
        assert not tech_flags_for_developed, (
            f"'Developed' was incorrectly flagged as an unsupported tech term: "
            f"{[f.message for f in tech_flags_for_developed]}"
        )

    def test_unsupported_tech_still_flagged_after_verb_exclusion(self) -> None:
        """After excluding common verbs, real unsupported technology names must still be flagged."""
        source = "Built data pipelines using Python scripts."
        tailored = "Built data pipelines using Python and Kubernetes orchestration."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        kubernetes_flag = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "Kubernetes" in f.message
        ]
        assert kubernetes_flag, (
            f"Expected UNSUPPORTED_CLAIM for 'Kubernetes' even after verb exclusions, "
            f"got: {[f.message for f in flags]}"
        )

    def test_low_overlap_produces_warning(self) -> None:
        """A tailored bullet with very low token overlap vs. source must produce a warning."""
        source = "Helped organize office supplies and filing systems."
        tailored = "Architected distributed microservices infrastructure using Kafka and Kubernetes."
        flags = self._check(tailored=tailored, source_bullet=source, location="work[0].bullets[0]")
        overlap_flags = [
            f for f in flags
            if f.flag_type == FlagType.UNSUPPORTED_CLAIM and "overlap" in f.message.lower()
        ]
        assert overlap_flags, (
            f"Expected low-overlap flag, got: {[f.message for f in flags]}"
        )

    def test_empty_tailored_returns_no_flags(self) -> None:
        """An empty tailored string produces no claim flags (structural check handled elsewhere)."""
        flags = self._check(tailored="", source_bullet="Some source.", location="loc")
        assert flags == []

    def test_flag_location_is_propagated(self) -> None:
        """The location parameter must appear in all returned flags."""
        source = "Helped with some tasks."
        tailored = "Led the entire team strategy and owned the roadmap."
        flags = self._check(tailored=tailored, source_bullet=source, location="section.bullets[3]")
        for f in flags:
            assert f.location == "section.bullets[3]", f"Wrong location: {f.location!r}"


# ---------------------------------------------------------------------------
# validate_resume() tests
# ---------------------------------------------------------------------------

class TestValidateResume:
    """Tests for the full TailoredResume validation pipeline."""

    def setup_method(self) -> None:
        from app.validation.validator import validate_resume
        self._validate = validate_resume

    def test_well_formed_resume_passes(self) -> None:
        """A clean resume with proper evidence should pass validation."""
        resume = _resume()
        report = self._validate(resume)
        assert isinstance(report, ValidationReport)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert not critical, f"Unexpected critical flags: {[f.message for f in critical]}"

    def test_artifact_id_is_resume_id(self) -> None:
        resume = _resume()
        report = self._validate(resume)
        assert report.artifact_id == resume.resume_id

    def test_empty_tailored_field_is_critical(self) -> None:
        """A bullet with an empty tailored field must produce a CRITICAL flag."""
        bullet = _bullet(tailored="")
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_empty_original_field_is_critical(self) -> None:
        """A bullet with an empty original field must produce a CRITICAL flag."""
        bullet = _bullet(original="")
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_empty_source_bullet_is_critical(self) -> None:
        """A bullet whose evidence has an empty source_bullet must produce a CRITICAL flag."""
        bullet = _bullet(evidence=_ev(source_bullet=""))
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_empty_source_section_is_critical(self) -> None:
        """A bullet whose evidence has an empty source_section must produce a CRITICAL flag."""
        bullet = _bullet(evidence=_ev(source_section=""))
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_confidence_zero_produces_unchanged_output_info_flag(self) -> None:
        """Confidence=0.0 (unchanged bullet) must produce an INFO flag of type UNCHANGED_OUTPUT."""
        bullet = _bullet(evidence=_ev(confidence=0.0))
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        info_unchanged = [
            f for f in report.flags
            if f.severity == FlagSeverity.INFO and f.flag_type == FlagType.UNCHANGED_OUTPUT
        ]
        assert info_unchanged, (
            f"Expected INFO/UNCHANGED_OUTPUT flag, got: {[(f.severity, f.flag_type) for f in report.flags]}"
        )

    def test_low_confidence_produces_low_confidence_warning(self) -> None:
        """Confidence below 0.5 (but > 0) must produce a WARNING of type LOW_CONFIDENCE."""
        bullet = _bullet(evidence=_ev(confidence=0.3))
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        warnings = [
            f for f in report.flags
            if f.severity == FlagSeverity.WARNING and f.flag_type == FlagType.LOW_CONFIDENCE
        ]
        assert warnings, (
            f"Expected LOW_CONFIDENCE warning, got: {[(f.severity, f.flag_type) for f in report.flags]}"
        )

    def test_empty_sections_dict_produces_warning(self) -> None:
        """A resume with no sections at all must produce an EMPTY_CONTENT warning."""
        resume = _resume(sections={})
        report = self._validate(resume)
        warnings = [
            f for f in report.flags
            if f.flag_type == FlagType.EMPTY_CONTENT
        ]
        assert warnings, (
            f"Expected EMPTY_CONTENT flag, got: {[(f.flag_type, f.message) for f in report.flags]}"
        )

    def test_empty_bullet_list_in_section_produces_warning(self) -> None:
        """A section present in the dict but with an empty bullet list must produce a warning."""
        resume = _resume(sections={"work_experience[0] — Acme — Eng": []})
        report = self._validate(resume)
        warnings = [f for f in report.flags if f.flag_type == FlagType.EMPTY_CONTENT]
        assert warnings

    def test_summary_without_evidence_links_produces_missing_evidence_warning(self) -> None:
        """A non-empty summary with no evidence_links must produce a MISSING_EVIDENCE warning."""
        summary = _grounded(text="Experienced engineer.", evidence_links=[])
        resume = _resume(summary=summary)
        report = self._validate(resume)
        missing_ev = [f for f in report.flags if f.flag_type == FlagType.MISSING_EVIDENCE]
        assert missing_ev, (
            f"Expected MISSING_EVIDENCE flag, got: {[f.flag_type for f in report.flags]}"
        )

    def test_summary_evidence_with_empty_source_bullet_is_critical(self) -> None:
        """A summary evidence link with an empty source_bullet must produce a CRITICAL flag."""
        ev = _ev(source_bullet="")
        summary = _grounded(text="Experienced engineer.", evidence_links=[ev])
        resume = _resume(summary=summary)
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_passed_false_when_critical_flag_present(self) -> None:
        bullet = _bullet(tailored="")
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        assert report.passed is False

    def test_passed_true_with_only_warnings(self) -> None:
        bullet = _bullet(evidence=_ev(confidence=0.3))
        resume = _resume(sections={"work_experience[0] — Acme — Eng": [bullet]})
        report = self._validate(resume)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert not critical
        assert report.passed is True


# ---------------------------------------------------------------------------
# validate_cover_letter() tests
# ---------------------------------------------------------------------------

class TestValidateCoverLetter:
    """Tests for the CoverLetterDraft validation pipeline."""

    def setup_method(self) -> None:
        from app.validation.validator import validate_cover_letter
        self._validate = validate_cover_letter

    def test_well_formed_cover_letter_passes(self) -> None:
        cl = _cover_letter()
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert not critical
        assert report.passed

    def test_artifact_id_is_draft_id(self) -> None:
        cl = _cover_letter()
        report = self._validate(cl)
        assert report.artifact_id == cl.draft_id

    def test_empty_body_is_critical(self) -> None:
        cl = _cover_letter(body="")
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_whitespace_only_body_is_critical(self) -> None:
        cl = _cover_letter(body="   \n  ")
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical

    def test_no_evidence_links_produces_missing_evidence_warning(self) -> None:
        cl = _cover_letter(evidence_links=[])
        report = self._validate(cl)
        missing_ev = [f for f in report.flags if f.flag_type == FlagType.MISSING_EVIDENCE]
        assert missing_ev, (
            f"Expected MISSING_EVIDENCE flag, got: {[f.flag_type for f in report.flags]}"
        )

    def test_evidence_with_empty_source_bullet_is_critical(self) -> None:
        cl = _cover_letter(evidence_links=[_ev(source_bullet="")])
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_evidence_with_empty_source_section_is_critical(self) -> None:
        cl = _cover_letter(evidence_links=[_ev(source_section="")])
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert critical
        assert not report.passed

    def test_passed_false_when_critical_flag_present(self) -> None:
        cl = _cover_letter(body="")
        report = self._validate(cl)
        assert report.passed is False

    def test_passed_true_with_only_missing_evidence_warning(self) -> None:
        cl = _cover_letter(evidence_links=[])
        report = self._validate(cl)
        critical = [f for f in report.flags if f.severity == FlagSeverity.CRITICAL]
        assert not critical
        assert report.passed is True


# ---------------------------------------------------------------------------
# ValidationReport schema tests
# ---------------------------------------------------------------------------

class TestValidationReport:
    """Tests for the ValidationReport schema, specifically the computed passed field."""

    def test_passed_true_with_no_flags(self) -> None:
        report = ValidationReport(artifact_id="test_001", flags=[])
        assert report.passed is True

    def test_passed_true_with_only_warnings(self) -> None:
        report = ValidationReport(
            artifact_id="test_001",
            flags=[_flag(severity=FlagSeverity.WARNING)],
        )
        assert report.passed is True

    def test_passed_true_with_only_info_flags(self) -> None:
        report = ValidationReport(
            artifact_id="test_001",
            flags=[_flag(severity=FlagSeverity.INFO)],
        )
        assert report.passed is True

    def test_passed_false_with_critical_flag(self) -> None:
        report = ValidationReport(
            artifact_id="test_001",
            flags=[_flag(severity=FlagSeverity.CRITICAL)],
        )
        assert report.passed is False

    def test_passed_false_with_mixed_flags_including_critical(self) -> None:
        report = ValidationReport(
            artifact_id="test_001",
            flags=[
                _flag(severity=FlagSeverity.WARNING),
                _flag(severity=FlagSeverity.CRITICAL),
                _flag(severity=FlagSeverity.INFO),
            ],
        )
        assert report.passed is False

    def test_artifact_id_stored(self) -> None:
        report = ValidationReport(artifact_id="my_artifact_123", flags=[])
        assert report.artifact_id == "my_artifact_123"

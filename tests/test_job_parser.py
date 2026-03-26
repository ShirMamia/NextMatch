"""
Tests for Slice 3 — Job Parsing and Deduplication.

Covers:
  - job_parser.parse_job: happy path (mocked LLM), description_raw preservation,
    required vs preferred requirements, job_id generation, empty input guard,
    missing title / company ValueError, LLMParseError propagation
  - PDF extraction integration path: pdfplumber.open is mocked so the real
    extract_text_from_bytes() logic runs, and the result flows into parse_job
  - deduper.is_duplicate: exact match, case-insensitive match, different company,
    empty list
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.discovery.deduper import is_duplicate
from app.parsers.job_parser import parse_job
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.services import pdf_reader  # module reference — required for correct mock targeting
from app.services.llm_client import LLMParseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source() -> JobSource:
    return JobSource(
        source_type="manual",
        source_name="manual",
        ingested_at=datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc),
    )


def _make_llm_result(**overrides) -> dict:
    """Return a minimal valid _JobParseResult dict."""
    base = {
        "title": "Senior Backend Engineer",
        "company": "TechCo",
        "location": "Remote",
        "is_remote": True,
        "requirements": [
            {
                "text": "5+ years of Python experience",
                "is_required": True,
                "skill_tags": ["Python"],
            },
            {
                "text": "Experience with Kubernetes (nice to have)",
                "is_required": False,
                "skill_tags": ["Kubernetes"],
            },
        ],
        "seniority_level": "senior",
        "employment_type": "full-time",
    }
    base.update(overrides)
    return base


def _make_parse_result(data: dict):
    """Construct a _JobParseResult from a dict.

    Uses _JobParseResult directly as white-box testing of the parser boundary:
    we want to verify that parse_job correctly promotes this intermediate type
    to a full JobPosting, not that call_llm_structured works end-to-end.
    """
    from app.parsers.job_parser import _JobParseResult  # type: ignore[attr-defined]
    return _JobParseResult.model_validate(data)


def _make_job_posting(title: str = "Senior Backend Engineer", company: str = "TechCo") -> JobPosting:
    """Return a minimal JobPosting for deduper tests."""
    return JobPosting(
        job_id="job_test_001",
        title=title,
        company=company,
        description_raw=f"{title} at {company}.",
        source=_make_source(),
    )


# ---------------------------------------------------------------------------
# parse_job tests
# ---------------------------------------------------------------------------

class TestParseJob:
    def test_returns_job_posting(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, _make_source())

        assert isinstance(job, JobPosting)

    def test_description_raw_preserved_verbatim(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, _make_source())

        assert job.description_raw == sample_job_raw_text

    def test_job_id_generated(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, _make_source())

        assert job.job_id
        assert len(job.job_id) == 32  # uuid4().hex

    def test_required_and_preferred_requirements(self, sample_job_raw_text):
        """is_required=True and is_required=False must be faithfully preserved."""
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, _make_source())

        required = [r for r in job.requirements if r.is_required]
        preferred = [r for r in job.requirements if not r.is_required]
        assert len(required) == 1
        assert len(preferred) == 1
        assert "Python" in required[0].skill_tags
        assert "Kubernetes" in preferred[0].skill_tags

    def test_parsed_fields_match_llm_output(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, _make_source())

        assert job.title == "Senior Backend Engineer"
        assert job.company == "TechCo"
        assert job.location == "Remote"
        assert job.is_remote is True
        assert job.seniority_level == "senior"
        assert job.employment_type == "full-time"

    def test_source_preserved(self, sample_job_raw_text):
        """The source passed by the caller must be preserved on the JobPosting."""
        source = JobSource(source_type="saved", source_name="techco_jd.pdf")
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(sample_job_raw_text, source)

        assert job.source.source_type == "saved"
        assert job.source.source_name == "techco_jd.pdf"

    def test_empty_text_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            parse_job("   ", _make_source())

    def test_missing_title_raises_value_error(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result(title=None)),
        ):
            with pytest.raises(ValueError, match="title"):
                parse_job(sample_job_raw_text, _make_source())

    def test_missing_company_raises_value_error(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result(company=None)),
        ):
            with pytest.raises(ValueError, match="[Cc]ompany"):
                parse_job(sample_job_raw_text, _make_source())

    def test_llm_parse_error_propagates(self, sample_job_raw_text):
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            side_effect=LLMParseError("bad json", raw_response="..."),
        ):
            with pytest.raises(LLMParseError):
                parse_job(sample_job_raw_text, _make_source())


# ---------------------------------------------------------------------------
# PDF extraction integration path
# ---------------------------------------------------------------------------

class TestPdfToParseJobIntegration:
    """Verify the PDF ingestion path: pdfplumber pages → extracted text → JobPosting.

    pdfplumber.open is mocked so extract_text_from_bytes() runs its real logic.
    The extracted text is then traced through parse_job to verify description_raw
    preservation and the full Slice 3 PDF ingestion contract.
    """

    def test_extracts_text_from_pages_and_flows_into_job_posting(self):
        """Real extract_text_from_bytes() logic runs; extracted text reaches parse_job.

        Two fake PDF pages:
          - Page 1 returns job description text.
          - Page 2 returns None (simulates an image-only page — must be skipped).
        """
        page1_text = (
            "Senior Backend Engineer — TechCo\n"
            "Remote | Full-time\n\n"
            "Requirements:\n"
            "- 5+ years Python\n"
            "- Kafka experience (nice to have)"
        )

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = page1_text
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = None  # image-only page

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [mock_page1, mock_page2]
            extracted = pdf_reader.extract_text_from_bytes(b"%PDF-fake", "techco_jd.pdf")

        assert extracted == page1_text

        source = JobSource(source_type="saved", source_name="techco_jd.pdf")
        with patch(
            "app.parsers.job_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            job = parse_job(extracted, source)

        # description_raw must preserve the exact string from the PDF reader.
        assert job.description_raw == page1_text


# ---------------------------------------------------------------------------
# Deduper tests
# ---------------------------------------------------------------------------

class TestDeduper:
    def test_exact_match_is_duplicate(self):
        job = _make_job_posting("Senior Backend Engineer", "TechCo")
        existing = [_make_job_posting("Senior Backend Engineer", "TechCo")]
        assert is_duplicate(job, existing) is True

    def test_case_insensitive_dedup(self):
        """Normalization must make deduplication case-insensitive."""
        job = _make_job_posting("senior backend engineer", "techco")
        existing = [_make_job_posting("Senior Backend Engineer", "TechCo")]
        assert is_duplicate(job, existing) is True

    def test_punctuation_insensitive_dedup(self):
        """Punctuation differences must not prevent duplicate detection."""
        job = _make_job_posting("Sr. Backend Engineer", "Tech-Co")
        existing = [_make_job_posting("Sr Backend Engineer", "TechCo")]
        assert is_duplicate(job, existing) is True

    def test_different_company_is_not_duplicate(self):
        """Same title at a different company must not be considered a duplicate."""
        job = _make_job_posting("Senior Backend Engineer", "OtherCorp")
        existing = [_make_job_posting("Senior Backend Engineer", "TechCo")]
        assert is_duplicate(job, existing) is False

    def test_different_title_is_not_duplicate(self):
        """Same company, different title must not be considered a duplicate."""
        job = _make_job_posting("Frontend Engineer", "TechCo")
        existing = [_make_job_posting("Senior Backend Engineer", "TechCo")]
        assert is_duplicate(job, existing) is False

    def test_empty_list_is_not_duplicate(self):
        job = _make_job_posting()
        assert is_duplicate(job, []) is False

    def test_duplicate_detected_among_multiple_existing(self):
        """Duplicate detection must work when existing_jobs has multiple entries."""
        job = _make_job_posting("Staff Engineer", "Acme")
        existing = [
            _make_job_posting("Senior Backend Engineer", "TechCo"),
            _make_job_posting("Staff Engineer", "Acme"),
            _make_job_posting("Frontend Engineer", "OtherCo"),
        ]
        assert is_duplicate(job, existing) is True


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_job_raw_text() -> str:
    return (
        "TechCo is looking for a Senior Backend Engineer to join our platform team.\n\n"
        "Requirements:\n"
        "- 5+ years of Python experience\n"
        "- Experience with distributed systems\n"
        "- Strong REST API knowledge\n\n"
        "Nice to have:\n"
        "- Experience with Kubernetes\n\n"
        "We offer remote-friendly work and competitive compensation."
    )

"""
Tests for Slice 2 — CV Parsing.

Covers:
  - text_cleaner.clean_cv_text: whitespace, HTML, blank-line normalization
  - cv_parser.parse_cv: happy path (mocked LLM), raw_text preservation,
    is_current / end_date enforcement, empty input guard
  - cv_parser.parse_cv: LLMParseError propagation
  - PDF extraction integration path: pdfplumber.open is mocked so the real
    extract_text_from_bytes() logic runs; the extracted text is then traced
    through parse_cv to verify the full Slice 2 PDF ingestion contract
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.parsers.text_cleaner import clean_cv_text
from app.parsers.cv_parser import parse_cv
from app.schemas.candidate import CandidateProfile
from app.services import pdf_reader  # module reference — required for correct mock targeting
from app.services.llm_client import LLMParseError


# ---------------------------------------------------------------------------
# text_cleaner tests
# ---------------------------------------------------------------------------

class TestCleanCvText:
    def test_returns_empty_for_blank_input(self):
        assert clean_cv_text("") == ""
        assert clean_cv_text("   \n\t  ") == ""

    def test_strips_html_tags(self):
        result = clean_cv_text("<b>Senior Engineer</b> at <em>Acme</em>")
        assert "<b>" not in result
        assert "<em>" not in result
        assert "Senior Engineer" in result
        assert "Acme" in result

    def test_collapses_horizontal_whitespace(self):
        result = clean_cv_text("Name:\t\t Jane   Smith")
        assert "\t" not in result
        assert "  " not in result  # no double spaces

    def test_collapses_excess_blank_lines(self):
        text = "Section A\n\n\n\n\nSection B"
        result = clean_cv_text(text)
        assert "\n\n\n" not in result
        assert "Section A" in result
        assert "Section B" in result

    def test_normalises_crlf(self):
        result = clean_cv_text("Line A\r\nLine B\r\nLine C")
        assert "\r" not in result
        assert "Line A" in result
        assert "Line B" in result

    def test_strips_leading_trailing_whitespace(self):
        result = clean_cv_text("  \n  hello  \n  ")
        assert result == "hello"

    def test_preserves_content(self):
        raw = "Jane Smith | jane@example.com\nSenior Engineer with 5 years experience."
        result = clean_cv_text(raw)
        assert "Jane Smith" in result
        assert "jane@example.com" in result
        assert "Senior Engineer" in result


# ---------------------------------------------------------------------------
# Helpers for cv_parser tests
# ---------------------------------------------------------------------------

def _make_llm_result(**overrides) -> dict:
    """Return a minimal valid _CVParseResult dict."""
    base = {
        "name": "Jane Smith",
        "email": "jane@example.com",
        "location": "Tel Aviv, Israel",
        "summary": "Senior engineer with 6 years of experience.",
        "skills": ["Python", "Kafka"],
        "work_experience": [
            {
                "company": "Acme Corp",
                "title": "Senior Software Engineer",
                "start_date": "2021-03",
                "end_date": None,
                "is_current": True,
                "bullets": ["Led migration to microservices."],
                "skills_used": ["Python", "Kafka"],
            }
        ],
        "education": [
            {
                "institution": "State University",
                "degree": "B.Sc.",
                "field": "Computer Science",
                "graduation_year": 2018,
            }
        ],
        "languages": ["English", "Hebrew"],
    }
    base.update(overrides)
    return base


def _make_parse_result(data: dict):
    """Construct a _CVParseResult from a dict.

    Uses _CVParseResult directly as white-box testing of the parser boundary:
    we want to verify that parse_cv correctly promotes this intermediate type
    to a full CandidateProfile, not that call_llm_structured works end-to-end.
    """
    from app.parsers.cv_parser import _CVParseResult  # type: ignore[attr-defined]
    return _CVParseResult.model_validate(data)


# ---------------------------------------------------------------------------
# cv_parser tests
# ---------------------------------------------------------------------------

class TestParseCv:
    def test_returns_candidate_profile(self, sample_candidate_raw_text):
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            profile = parse_cv(sample_candidate_raw_text)

        assert isinstance(profile, CandidateProfile)

    def test_raw_text_preserved_verbatim(self, sample_candidate_raw_text):
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            profile = parse_cv(sample_candidate_raw_text)

        assert profile.raw_text == sample_candidate_raw_text

    def test_candidate_id_generated(self, sample_candidate_raw_text):
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            profile = parse_cv(sample_candidate_raw_text)

        assert profile.candidate_id  # non-empty string
        assert len(profile.candidate_id) == 32  # uuid4().hex

    def test_parsed_fields_match_llm_output(self, sample_candidate_raw_text):
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            profile = parse_cv(sample_candidate_raw_text)

        assert profile.name == "Jane Smith"
        assert profile.email == "jane@example.com"
        assert profile.location == "Tel Aviv, Israel"
        assert "Python" in profile.skills
        assert len(profile.work_experience) == 1
        assert len(profile.education) == 1

    def test_is_current_clears_end_date(self, sample_candidate_raw_text):
        """parse_cv must clear end_date when is_current=True, even if the LLM set it."""
        bad_we = {
            "company": "Acme",
            "title": "Engineer",
            "start_date": "2021-03",
            "end_date": "2025-01",   # LLM gave an end_date even though is_current=True
            "is_current": True,
            "bullets": [],
            "skills_used": [],
        }
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result(work_experience=[bad_we])),
        ):
            profile = parse_cv(sample_candidate_raw_text)

        we = profile.work_experience[0]
        assert we.is_current is True
        assert we.end_date is None  # enforced by parse_cv promotion step

    def test_empty_text_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            parse_cv("   ")

    def test_llm_parse_error_propagates(self, sample_candidate_raw_text):
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            side_effect=LLMParseError("bad json", raw_response="..."),
        ):
            with pytest.raises(LLMParseError):
                parse_cv(sample_candidate_raw_text)


# ---------------------------------------------------------------------------
# PDF extraction integration path
# ---------------------------------------------------------------------------

class TestPdfToParseCvIntegration:
    """Verify the full PDF ingestion path: pdfplumber pages → extracted text → CandidateProfile.

    Mocking strategy: patch "pdfplumber.open" directly on the pdfplumber module
    object in sys.modules. extract_text_from_bytes() does a lazy `import pdfplumber`
    inside the function; that import resolves from sys.modules, so patching
    `pdfplumber.open` is the correct boundary — it lets the real extraction loop
    (page iteration, extract_text() calls, None-page skipping, join) run for real.

    extract_text_from_bytes() is NOT mocked; only the pdfplumber dependency below it is.
    """

    def test_extracts_text_from_pages_and_flows_into_candidate_profile(self):
        """Real extract_text_from_bytes() logic runs; extracted text reaches parse_cv.

        Two fake PDF pages:
          - Page 1 returns CV text.
          - Page 2 returns None (simulates an image-only page).

        Verifies that:
          - extract_text_from_bytes collects page 1 text and skips page 2.
          - The extracted string is passed to parse_cv without modification.
          - CandidateProfile.raw_text preserves the exact extracted string.
        """
        page1_text = (
            "Jane Smith | jane@example.com\n"
            "Senior Software Engineer at Acme Corp (2021 \u2013 present)\n"
            "SKILLS: Python, Kafka"
        )

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = page1_text

        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = None  # image-only page — must be skipped

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [mock_page1, mock_page2]
            # extract_text_from_bytes() runs its real logic here.
            extracted = pdf_reader.extract_text_from_bytes(b"%PDF-fake", "cv.pdf")

        # Only page 1 text should appear; page 2 (None) must be skipped.
        assert extracted == page1_text

        # Trace through parse_cv and verify the Slice 2 raw_text preservation contract.
        with patch(
            "app.parsers.cv_parser.call_llm_structured",
            return_value=_make_parse_result(_make_llm_result()),
        ):
            profile = parse_cv(extracted)

        assert profile.raw_text == page1_text


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_candidate_raw_text() -> str:
    return (
        "Jane Smith | jane@example.com | Tel Aviv, Israel\n"
        "Senior Software Engineer with 6 years of experience in Python.\n\n"
        "EXPERIENCE\n"
        "Acme Corp \u2014 Senior Software Engineer (Mar 2021 \u2013 present)\n"
        "- Led migration to microservices.\n\n"
        "EDUCATION\n"
        "B.Sc. Computer Science, State University, 2018\n\n"
        "SKILLS\n"
        "Python, Kafka"
    )

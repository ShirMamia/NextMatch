"""
Shared test fixtures for NextMatch.

Provides minimal but realistic sample data for all test modules.
Fixtures are scoped to 'session' where the object is read-only,
and 'function' where tests may mutate the fixture.
"""
from __future__ import annotations

from datetime import timezone, datetime
from pathlib import Path

import pytest

from app.schemas.candidate import CandidateProfile, Education, WorkExperience
from app.schemas.job import JobPosting, JobRequirement, JobSource
from app.schemas.search import LocationPreference, SearchProfile


# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_work_experience() -> list[WorkExperience]:
    return [
        WorkExperience(
            company="Acme Corp",
            title="Senior Software Engineer",
            start_date="2021-03",
            end_date=None,
            is_current=True,
            bullets=[
                "Led migration of monolithic API to microservices, reducing p99 latency by 40%.",
                "Mentored three junior engineers and conducted weekly code reviews.",
                "Designed and shipped a real-time event pipeline using Kafka and Python.",
            ],
            skills_used=["Python", "Kafka", "Docker", "PostgreSQL"],
        ),
        WorkExperience(
            company="Beta Startup",
            title="Software Engineer",
            start_date="2018-06",
            end_date="2021-02",
            is_current=False,
            bullets=[
                "Built REST APIs in FastAPI serving 500K daily active users.",
                "Implemented CI/CD pipeline using GitHub Actions and AWS ECS.",
            ],
            skills_used=["Python", "FastAPI", "AWS", "GitHub Actions"],
        ),
    ]


@pytest.fixture(scope="session")
def sample_education() -> list[Education]:
    return [
        Education(
            institution="State University",
            degree="B.Sc.",
            field="Computer Science",
            graduation_year=2018,
        )
    ]


@pytest.fixture(scope="session")
def sample_candidate_profile(
    sample_work_experience: list[WorkExperience],
    sample_education: list[Education],
) -> CandidateProfile:
    raw = (
        "Jane Smith | jane@example.com | Tel Aviv, Israel\n"
        "Senior Software Engineer with 6 years of experience in Python, distributed systems, "
        "and cloud infrastructure.\n\n"
        "EXPERIENCE\n"
        "Acme Corp — Senior Software Engineer (Mar 2021 – present)\n"
        "- Led migration of monolithic API to microservices, reducing p99 latency by 40%.\n"
        "- Mentored three junior engineers and conducted weekly code reviews.\n"
        "- Designed and shipped a real-time event pipeline using Kafka and Python.\n\n"
        "Beta Startup — Software Engineer (Jun 2018 – Feb 2021)\n"
        "- Built REST APIs in FastAPI serving 500K daily active users.\n"
        "- Implemented CI/CD pipeline using GitHub Actions and AWS ECS.\n\n"
        "EDUCATION\n"
        "B.Sc. Computer Science, State University, 2018\n\n"
        "SKILLS\n"
        "Python, FastAPI, Kafka, Docker, PostgreSQL, AWS, GitHub Actions, Redis"
    )
    return CandidateProfile(
        candidate_id="cand_test_001",
        name="Jane Smith",
        email="jane@example.com",
        location="Tel Aviv, Israel",
        summary=(
            "Senior Software Engineer with 6 years of experience in Python, "
            "distributed systems, and cloud infrastructure."
        ),
        skills=["Python", "FastAPI", "Kafka", "Docker", "PostgreSQL", "AWS", "GitHub Actions", "Redis"],
        work_experience=sample_work_experience,
        education=sample_education,
        languages=["English", "Hebrew"],
        raw_text=raw,
        parsed_at=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Job posting
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_job_source() -> JobSource:
    return JobSource(
        source_type="manual",
        source_name="manual",
        url=None,
        ingested_at=datetime(2026, 3, 25, 9, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture(scope="session")
def sample_job_posting(sample_job_source: JobSource) -> JobPosting:
    description = (
        "TechCo is looking for a Senior Backend Engineer to join our platform team.\n\n"
        "Requirements:\n"
        "- 5+ years of Python experience\n"
        "- Experience with distributed systems and message queues (Kafka preferred)\n"
        "- Strong knowledge of REST API design\n"
        "- Experience with cloud infrastructure (AWS or GCP)\n\n"
        "Nice to have:\n"
        "- Experience with Kubernetes\n"
        "- Familiarity with Go\n\n"
        "We offer remote-friendly work and competitive compensation."
    )
    return JobPosting(
        job_id="job_test_001",
        title="Senior Backend Engineer",
        company="TechCo",
        location="Remote",
        is_remote=True,
        description_raw=description,
        requirements=[
            JobRequirement(text="5+ years of Python experience", is_required=True, skill_tags=["Python"]),
            JobRequirement(text="Experience with distributed systems and message queues (Kafka preferred)", is_required=True, skill_tags=["Kafka", "distributed systems"]),
            JobRequirement(text="Strong knowledge of REST API design", is_required=True, skill_tags=["REST", "API"]),
            JobRequirement(text="Experience with cloud infrastructure (AWS or GCP)", is_required=True, skill_tags=["AWS", "GCP"]),
            JobRequirement(text="Experience with Kubernetes", is_required=False, skill_tags=["Kubernetes"]),
            JobRequirement(text="Familiarity with Go", is_required=False, skill_tags=["Go"]),
        ],
        seniority_level="senior",
        employment_type="full-time",
        source=sample_job_source,
        normalized_at=datetime(2026, 3, 25, 9, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Search profile
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_search_profile() -> SearchProfile:
    return SearchProfile(
        search_id="search_test_001",
        name="Senior Backend Roles",
        target_roles=["Senior Backend Engineer", "Senior Software Engineer", "Staff Engineer"],
        required_skills=["Python", "REST API"],
        preferred_skills=["Kafka", "AWS", "Docker"],
        excluded_keywords=["PHP", "WordPress"],
        location_preference=LocationPreference(remote_ok=True),
        min_seniority="senior",
        max_seniority=None,
        industry_preferences=["SaaS", "FinTech"],
        created_at=datetime(2026, 3, 25, 8, 0, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """A temporary directory for FileStore tests."""
    return tmp_path / "data"

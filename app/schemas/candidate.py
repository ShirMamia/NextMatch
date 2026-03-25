"""
Candidate schema — Slice 1 foundation.

Intentionally minimal for V1. The following fields are candidates for later
slices if needed: headline, projects, certifications, publications.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator


class WorkExperience(BaseModel):
    model_config = {"extra": "forbid"}

    company: str
    title: str
    start_date: str | None = None  # Optional: LLM parsing may miss or mangle dates
    end_date: str | None = None
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_current_consistency(self) -> WorkExperience:
        if self.is_current and self.end_date is not None:
            raise ValueError(
                "is_current=True and a non-null end_date are mutually exclusive"
            )
        return self


class Education(BaseModel):
    model_config = {"extra": "forbid"}

    institution: str
    degree: str
    field: str
    graduation_year: int | None = None


class CandidateProfile(BaseModel):
    model_config = {"extra": "forbid"}

    candidate_id: str
    name: str
    email: str | None = None
    location: str | None = None
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    raw_text: str  # preserved verbatim; used as the grounding source for all validation
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

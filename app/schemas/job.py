"""
Job posting schema — Slice 1 foundation.

JobPosting is the normalized representation of any ingested job,
regardless of source. description_raw is always preserved for grounding.

Design note — requirements list:
A single list[JobRequirement] with is_required=True/False is the single
source of truth for both required and nice-to-have items. This maps cleanly
to how job descriptions are structured and avoids duplicate representation.
The matching scorer uses is_required to weight skill gaps differently.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class JobRequirement(BaseModel):
    model_config = {"extra": "forbid"}

    text: str
    is_required: bool = True  # False = nice-to-have / preferred
    skill_tags: list[str] = Field(default_factory=list)


class JobSource(BaseModel):
    model_config = {"extra": "forbid"}

    source_type: Literal["manual", "saved", "api"]
    source_name: str  # e.g. "manual", "greenhouse", "lever", "saved_file"
    url: str | None = None
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class JobPosting(BaseModel):
    model_config = {"extra": "forbid"}

    job_id: str
    title: str
    company: str
    location: str | None = None
    is_remote: bool | None = None  # None = not specified in the posting
    description_raw: str  # preserved verbatim; source of truth for validation
    requirements: list[JobRequirement] = Field(default_factory=list)
    seniority_level: str | None = None
    employment_type: str | None = None
    source: JobSource
    normalized_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

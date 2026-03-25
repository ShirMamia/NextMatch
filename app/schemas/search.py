"""
Search profile schema — Slice 1 foundation.

A SearchProfile describes what the candidate is looking for, used to rank
discovered jobs. Distinct from CandidateProfile (who the candidate is).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class LocationPreference(BaseModel):
    model_config = {"extra": "forbid"}

    city: str | None = None
    country: str | None = None
    # None = unspecified (no preference expressed), True/False = explicit preference
    remote_ok: bool | None = None


class SearchProfile(BaseModel):
    model_config = {"extra": "forbid"}

    search_id: str
    name: str
    target_roles: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    location_preference: LocationPreference = Field(
        default_factory=LocationPreference
    )
    min_seniority: str | None = None
    max_seniority: str | None = None
    industry_preferences: list[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

"""
Match result schema — Slice 1 foundation.

MatchResult represents the output of comparing a CandidateProfile against
a specific JobPosting. All scoring is deterministic (see matching/scorer.py).

Two distinct scores exist (see CLAUDE.md):
  - Search profile fit  (how well a job matches what the candidate wants)
  - Candidate-job fit   (how well the candidate matches a specific job)
MatchResult represents candidate-job fit only.

Score ownership:
The schema enforces valid ranges (0.0–1.0) for all score fields, but does
not own the scoring formula. overall_score is computed by matching/scorer.py
using the weights defined there. The schema is intentionally formula-agnostic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SkillMatch(BaseModel):
    model_config = {"extra": "forbid"}

    skill: str
    found_in_profile: bool
    # Zero or more source snippets that support the skill match assessment.
    evidence_snippets: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    model_config = {"extra": "forbid"}

    skills_score: float = Field(ge=0.0, le=1.0)
    experience_score: float = Field(ge=0.0, le=1.0)
    education_score: float = Field(ge=0.0, le=1.0)
    seniority_score: float = Field(ge=0.0, le=1.0)
    # Weighted composite; computed by matching/scorer.py.
    overall_score: float = Field(ge=0.0, le=1.0)


class MatchResult(BaseModel):
    model_config = {"extra": "forbid"}

    match_id: str
    candidate_id: str
    job_id: str
    score_breakdown: ScoreBreakdown
    skill_matches: list[SkillMatch] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

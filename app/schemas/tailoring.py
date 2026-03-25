"""
Tailoring schema — Slice 1 foundation.

TailoredResume is the primary artifact of the generation pipeline.
Every tailored claim carries a grounding structure back to source material,
enabling validation and user review before approval.

Truthfulness contract:
  - The system may rewrite, reorder, shorten, and prioritize content.
  - The system must not invent claims, metrics, tools, or experience.
  - Every tailored claim must be traceable to source evidence via EvidenceLink.
  - No TailoredResume may be saved as approved without passing validation.

Design note — summary and cover letter:
  - summary is a GroundedText: structured text with list[EvidenceLink],
    using the same evidence model as TailoredBullet for consistency.
  - cover_letter_draft is excluded from TailoredResume in Slice 1 and
    will be introduced in a later slice as its own grounded schema.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator


class EvidenceLink(BaseModel):
    """Maps a tailored claim back to its verbatim source material."""

    model_config = {"extra": "forbid"}

    source_bullet: str  # verbatim text from the source CV
    source_section: str  # path into CandidateProfile, e.g. "work_experience[0].bullets[2]"
    confidence: float = Field(ge=0.0, le=1.0)


class TailoredBullet(BaseModel):
    model_config = {"extra": "forbid"}

    original: str  # the unmodified source bullet
    tailored: str  # the rewritten bullet targeting the job
    evidence: EvidenceLink
    approved: bool = False


class GroundedText(BaseModel):
    """
    A free-form text block (e.g. summary) with structured evidence links.
    Uses the same EvidenceLink model as TailoredBullet for grounding consistency.
    """

    model_config = {"extra": "forbid"}

    text: str
    evidence_links: list[EvidenceLink] = Field(default_factory=list)


class TailoredResume(BaseModel):
    model_config = {"extra": "forbid"}

    resume_id: str
    candidate_id: str
    job_id: str
    match_id: str
    summary: GroundedText = Field(default_factory=lambda: GroundedText(text=""))
    # Section name → ordered list of tailored bullets.
    sections: dict[str, list[TailoredBullet]] = Field(default_factory=dict)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    approved_at: datetime | None = None
    approved: bool = False

    @model_validator(mode="after")
    def check_approval_consistency(self) -> TailoredResume:
        if self.approved and self.approved_at is None:
            raise ValueError("approved=True requires approved_at to be set")
        if not self.approved and self.approved_at is not None:
            raise ValueError("approved_at must be None when approved=False")
        return self

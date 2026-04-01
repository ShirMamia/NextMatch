"""
Validation schema — Slice 1 foundation, extended in Slice 7.

All models use Pydantic BaseModel and str Enum exclusively.
No dataclasses.

ValidationFlag is the atomic unit of validation output.
ValidationReport aggregates flags for a single validated artifact
(TailoredResume or CoverLetterDraft).

Severity levels:
  - CRITICAL: blocks approval (e.g. unsupported claim, missing evidence)
  - WARNING: user should review but does not block (e.g. low confidence)
  - INFO: informational annotation, no action required

FlagType semantics:
  - MISSING_EVIDENCE: a claim or section has no grounding evidence at all
  - UNSUPPORTED_CLAIM: a specific claim cannot be traced to the source evidence
  - UNCHANGED_OUTPUT: generated content was returned verbatim with no tailoring applied
  - LOW_CONFIDENCE: tailoring was applied but with low confidence
  - DUPLICATE: near-duplicate content detected across bullets or sections
  - INCONSISTENCY: contradictory claims within the same artifact
  - MALFORMED_OUTPUT: structurally invalid content (empty required fields, etc.)
  - EMPTY_CONTENT: a section or block is present but has no meaningful content

Consistency rule:
  ValidationReport.passed is computed automatically from the flags list.
  It is always True iff there are no CRITICAL-severity flags.
  Callers do not set passed manually; it is enforced by model_validator.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.utils.time import utc_now


class FlagSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class FlagType(str, Enum):
    MISSING_EVIDENCE = "missing_evidence"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    UNCHANGED_OUTPUT = "unchanged_output"
    LOW_CONFIDENCE = "low_confidence"
    DUPLICATE = "duplicate"
    INCONSISTENCY = "inconsistency"
    MALFORMED_OUTPUT = "malformed_output"
    EMPTY_CONTENT = "empty_content"


class ValidationFlag(BaseModel):
    model_config = {"extra": "forbid"}

    flag_id: str
    severity: FlagSeverity
    flag_type: FlagType
    message: str
    location: str  # section/bullet reference, e.g. "work_experience[0].bullets[2]"
    evidence: str | None = None  # supporting detail for the flag


class ValidationReport(BaseModel):
    model_config = {"extra": "forbid"}

    # artifact_id is the ID of the validated artifact — either a TailoredResume
    # (resume_id) or a CoverLetterDraft (draft_id).
    artifact_id: str
    flags: list[ValidationFlag] = Field(default_factory=list)
    # Computed automatically: True iff no CRITICAL flags are present.
    passed: bool = True
    validated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def compute_passed(self) -> ValidationReport:
        has_critical = any(
            f.severity == FlagSeverity.CRITICAL for f in self.flags
        )
        self.passed = not has_critical
        return self

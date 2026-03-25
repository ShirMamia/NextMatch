"""
Validation schema — Slice 1 foundation.

All models use Pydantic BaseModel and str Enum exclusively.
No dataclasses.

ValidationFlag is the atomic unit of validation output.
ValidationReport aggregates flags for a single TailoredResume.

Severity levels:
  - CRITICAL: blocks approval (e.g. unsupported claim, missing evidence)
  - WARNING: user should review but does not block (e.g. near-duplicate)
  - INFO: informational annotation, no action required

Consistency rule:
  ValidationReport.passed is computed automatically from the flags list.
  It is always True iff there are no CRITICAL-severity flags.
  Callers do not set passed manually; it is enforced by model_validator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FlagSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class FlagType(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    DUPLICATE = "duplicate"
    INCONSISTENCY = "inconsistency"
    LOW_CONFIDENCE = "low_confidence"
    MALFORMED_OUTPUT = "malformed_output"
    EMPTY_CONTENT = "empty_content"


class ValidationFlag(BaseModel):
    model_config = {"extra": "forbid"}

    flag_id: str
    severity: FlagSeverity
    flag_type: FlagType
    message: str
    location: str  # section/bullet reference, e.g. "sections.work_experience[0]"
    evidence: str | None = None  # supporting detail for the flag


class ValidationReport(BaseModel):
    model_config = {"extra": "forbid"}

    resume_id: str
    flags: list[ValidationFlag] = Field(default_factory=list)
    # Computed automatically: True iff no CRITICAL flags are present.
    passed: bool = True
    validated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def compute_passed(self) -> ValidationReport:
        has_critical = any(
            f.severity == FlagSeverity.CRITICAL for f in self.flags
        )
        self.passed = not has_critical
        return self

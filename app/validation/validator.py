"""
Validation orchestrator — Slice 7.

Provides two public entry points:
  validate_resume(resume)        → ValidationReport
  validate_cover_letter(cl)      → ValidationReport

All validation is fully deterministic. No LLM calls.
Both functions return a ValidationReport conforming to the existing schema.
The report's artifact_id is set to the resume_id or draft_id of the input.

Validation is a review gate only. This module does not:
  - save artifacts
  - approve artifacts
  - integrate with the application tracker
  - produce any side effects

Approval and save flows belong to Slice 8.
"""
from __future__ import annotations

import logging

from app.schemas.tailoring import CoverLetterDraft, TailoredResume
from app.schemas.validation import (
    FlagSeverity,
    FlagType,
    ValidationFlag,
    ValidationReport,
)
from app.utils.ids import generate_id
from app.validation import claim_checker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flag(
    severity: FlagSeverity,
    flag_type: FlagType,
    message: str,
    location: str,
    evidence: str | None = None,
) -> ValidationFlag:
    return ValidationFlag(
        flag_id=generate_id(),
        severity=severity,
        flag_type=flag_type,
        message=message,
        location=location,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Resume validation
# ---------------------------------------------------------------------------

def validate_resume(resume: TailoredResume) -> ValidationReport:
    """
    Validate a TailoredResume and return a structured ValidationReport.

    Checks:
      - Summary evidence links are present and non-empty
      - Each bullet has non-empty original, tailored, and evidence fields
      - Each bullet's confidence level is flagged appropriately
      - Claim checker runs on each bullet with non-empty tailored and source
      - Empty sections and empty bullet lists are flagged
    """
    flags: list[ValidationFlag] = []

    # --- Summary validation ---
    _validate_summary(resume, flags)

    # --- Section / bullet validation ---
    if not resume.sections:
        flags.append(_flag(
            FlagSeverity.WARNING,
            FlagType.EMPTY_CONTENT,
            "Tailored resume has no work experience sections — no bullets were generated.",
            "sections",
        ))
    else:
        for section_name, bullets in resume.sections.items():
            _validate_section(section_name, bullets, flags)

    return ValidationReport(artifact_id=resume.resume_id, flags=flags)


def _validate_summary(resume: TailoredResume, flags: list[ValidationFlag]) -> None:
    """Append summary-level flags to the flag list in place."""
    if not resume.summary.text.strip():
        # An empty summary is not an error — the profile may not have had one.
        return

    if not resume.summary.evidence_links:
        flags.append(_flag(
            FlagSeverity.WARNING,
            FlagType.MISSING_EVIDENCE,
            "Generated summary has no evidence links — grounding cannot be verified.",
            "summary",
        ))
        return

    for i, ev in enumerate(resume.summary.evidence_links):
        ev_loc = f"summary.evidence_links[{i}]"
        if not ev.source_bullet.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MALFORMED_OUTPUT,
                "Summary evidence link has an empty source_bullet.",
                ev_loc,
            ))
        if not ev.source_section.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MALFORMED_OUTPUT,
                "Summary evidence link has an empty source_section.",
                ev_loc,
            ))


def _validate_section(
    section_name: str,
    bullets: list,
    flags: list[ValidationFlag],
) -> None:
    """Append section- and bullet-level flags to the flag list in place."""
    if not bullets:
        flags.append(_flag(
            FlagSeverity.WARNING,
            FlagType.EMPTY_CONTENT,
            "Section has no tailored bullets.",
            section_name,
        ))
        return

    for i, bullet in enumerate(bullets):
        location = f"{section_name}.bullets[{i}]"

        # --- Structural integrity ---
        if not bullet.original.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MALFORMED_OUTPUT,
                "Tailored bullet has an empty 'original' field.",
                location,
            ))

        if not bullet.tailored.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MALFORMED_OUTPUT,
                "Tailored bullet has an empty 'tailored' field.",
                location,
            ))

        if not bullet.evidence.source_bullet.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MISSING_EVIDENCE,
                "Tailored bullet has no source evidence (source_bullet is empty).",
                location,
            ))

        if not bullet.evidence.source_section.strip():
            flags.append(_flag(
                FlagSeverity.CRITICAL,
                FlagType.MISSING_EVIDENCE,
                "Tailored bullet has no source evidence path (source_section is empty).",
                location,
            ))

        # --- Confidence-based quality signals ---
        if bullet.evidence.confidence == 0.0:
            flags.append(_flag(
                FlagSeverity.INFO,
                FlagType.UNCHANGED_OUTPUT,
                "Bullet was returned unchanged (confidence = 0.0) — no tailoring was applied.",
                location,
                evidence=bullet.tailored or bullet.original,
            ))
        elif bullet.evidence.confidence < 0.5:
            flags.append(_flag(
                FlagSeverity.WARNING,
                FlagType.LOW_CONFIDENCE,
                (
                    f"Low tailoring confidence ({int(bullet.evidence.confidence * 100)}%) — "
                    "this bullet may not be well targeted for this role."
                ),
                location,
                evidence=bullet.tailored,
            ))

        # --- Claim checking (only when both tailored and source are non-empty) ---
        if bullet.tailored.strip() and bullet.evidence.source_bullet.strip():
            claim_flags = claim_checker.check_bullet(
                tailored=bullet.tailored,
                source_bullet=bullet.evidence.source_bullet,
                location=location,
            )
            flags.extend(claim_flags)


# ---------------------------------------------------------------------------
# Cover letter validation
# ---------------------------------------------------------------------------

def validate_cover_letter(cl: CoverLetterDraft) -> ValidationReport:
    """
    Validate a CoverLetterDraft and return a structured ValidationReport.

    Checks:
      - Body is non-empty
      - Evidence links are present
      - Each evidence link has non-empty source_bullet and source_section
    """
    flags: list[ValidationFlag] = []

    if not cl.body.strip():
        flags.append(_flag(
            FlagSeverity.CRITICAL,
            FlagType.EMPTY_CONTENT,
            "Cover letter body is empty.",
            "body",
        ))

    if not cl.evidence_links:
        flags.append(_flag(
            FlagSeverity.WARNING,
            FlagType.MISSING_EVIDENCE,
            "Cover letter has no evidence links — grounding cannot be verified.",
            "evidence_links",
        ))
    else:
        for i, ev in enumerate(cl.evidence_links):
            location = f"evidence_links[{i}]"
            if not ev.source_bullet.strip():
                flags.append(_flag(
                    FlagSeverity.CRITICAL,
                    FlagType.MISSING_EVIDENCE,
                    "Cover letter evidence link has an empty source_bullet.",
                    location,
                ))
            if not ev.source_section.strip():
                flags.append(_flag(
                    FlagSeverity.CRITICAL,
                    FlagType.MISSING_EVIDENCE,
                    "Cover letter evidence link has an empty source_section.",
                    location,
                ))

    return ValidationReport(artifact_id=cl.draft_id, flags=flags)

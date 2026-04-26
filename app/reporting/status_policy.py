"""
Application status transition policy — Slice 11.

Single source of truth for which ApplicationStatus transitions are allowed.
No I/O, no Streamlit, no LLM.

Entry points:
  allowed_target_statuses(current)             → list[ApplicationStatus]
  is_valid_transition(current, target)          → bool
  explain_invalid_transition(current, target)   → str

Policy summary (see _TRANSITIONS for the complete machine):
  DISCOVERED   → SAVED
  SAVED        → TAILORED
  TAILORED     → APPROVED | APPLIED
  APPROVED     → APPLIED | TAILORED
  APPLIED      → INTERVIEWING | REJECTED | WITHDRAWN | TAILORED
  INTERVIEWING → OFFERED | REJECTED | WITHDRAWN | APPLIED
  OFFERED      → WITHDRAWN
  REJECTED     → (terminal)
  WITHDRAWN    → (terminal)

Design decisions:
  - TAILORED → APPLIED is allowed as a direct shortcut because the product
    creates records at TAILORED status and the tracker lets users record a
    direct submit without an explicit APPROVED step.
  - APPLIED → TAILORED and INTERVIEWING → APPLIED are correction backward
    moves, not "undo" features. The applied_at field is managed automatically
    by TrackerService so field consistency is preserved even when moving back.
  - REJECTED and WITHDRAWN are terminal. Once a candidate is rejected or
    withdraws, the lifecycle for that record is over. A new application to
    the same job would be a new ApplicationRecord.
  - OFFERED → WITHDRAWN is the only move from OFFERED, representing a
    candidate declining a received offer.

TrackerService.update_status is the enforcement point; it calls
is_valid_transition before any persistence.
"""
from __future__ import annotations

from app.schemas.application import ApplicationStatus

# ---------------------------------------------------------------------------
# Transition table — the single source of truth.
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.DISCOVERED: frozenset({
        ApplicationStatus.SAVED,
    }),
    ApplicationStatus.SAVED: frozenset({
        ApplicationStatus.TAILORED,
    }),
    ApplicationStatus.TAILORED: frozenset({
        ApplicationStatus.APPROVED,   # standard path: candidate approved the resume
        ApplicationStatus.APPLIED,    # direct shortcut: record a submission without an explicit APPROVED step
    }),
    ApplicationStatus.APPROVED: frozenset({
        ApplicationStatus.APPLIED,    # standard: submit the approved resume
        ApplicationStatus.TAILORED,   # correction: go back to re-tailor before submitting
    }),
    ApplicationStatus.APPLIED: frozenset({
        ApplicationStatus.INTERVIEWING,  # selected for an interview
        ApplicationStatus.REJECTED,      # application rejected by employer
        ApplicationStatus.WITHDRAWN,     # candidate withdrew the application
        ApplicationStatus.TAILORED,      # correction: revert before the application was submitted
    }),
    ApplicationStatus.INTERVIEWING: frozenset({
        ApplicationStatus.OFFERED,    # employer extended an offer
        ApplicationStatus.REJECTED,   # rejected after the interview stage
        ApplicationStatus.WITHDRAWN,  # candidate withdrew during interviewing
        ApplicationStatus.APPLIED,    # correction: revert to applied stage
    }),
    ApplicationStatus.OFFERED: frozenset({
        ApplicationStatus.WITHDRAWN,  # candidate declined the offer
    }),
    ApplicationStatus.REJECTED: frozenset(),   # terminal — no further transitions
    ApplicationStatus.WITHDRAWN: frozenset(),  # terminal — no further transitions
}

# Validate at import time: every ApplicationStatus must appear as a key.
assert set(_TRANSITIONS.keys()) == set(ApplicationStatus), (
    "status_policy._TRANSITIONS is missing entries for some ApplicationStatus values"
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def allowed_target_statuses(current: ApplicationStatus) -> list[ApplicationStatus]:
    """Return the list of valid target statuses from current.

    Returns an empty list if current is a terminal status.
    The order of the list follows enum-definition order for stable UI rendering.
    """
    targets = _TRANSITIONS.get(current, frozenset())
    # Return in enum-definition order for deterministic, stable UI.
    return [s for s in ApplicationStatus if s in targets]


def is_valid_transition(
    current: ApplicationStatus,
    target: ApplicationStatus,
) -> bool:
    """Return True if moving from current to target is a permitted transition."""
    return target in _TRANSITIONS.get(current, frozenset())


def explain_invalid_transition(
    current: ApplicationStatus,
    target: ApplicationStatus,
) -> str:
    """Return a human-readable explanation of why this transition is blocked.

    Always returns a non-empty string.
    Callers should only invoke this when is_valid_transition returns False.
    """
    allowed = allowed_target_statuses(current)

    if not allowed:
        return (
            f"'{current.value}' is a terminal status — "
            "no further transitions are available for this application."
        )

    allowed_labels = ", ".join(f"'{s.value}'" for s in allowed)
    return (
        f"Cannot move from '{current.value}' to '{target.value}'. "
        f"Allowed transitions from '{current.value}': {allowed_labels}."
    )

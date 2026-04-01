"""
Validation panel — Streamlit component for displaying a ValidationReport.

Renders a structured summary of validation results for a generated artifact
(TailoredResume or CoverLetterDraft). The panel is read-only — it surfaces
flags for user review but does not implement approval or save logic.

Display structure:
  1. Pass/fail banner with overall result.
  2. Severity counts (critical / warning / info).
  3. Per-severity flag list with location, type, and detail.

Approval and save actions belong to Slice 8 and are explicitly not present here.
"""
from __future__ import annotations

import streamlit as st

from app.schemas.validation import FlagSeverity, FlagType, ValidationReport


# Map severity to a human-readable label and Streamlit display method.
_SEVERITY_LABEL: dict[FlagSeverity, str] = {
    FlagSeverity.CRITICAL: "Critical",
    FlagSeverity.WARNING: "Warning",
    FlagSeverity.INFO: "Info",
}

# Map FlagType to a short, user-friendly label.
_TYPE_LABEL: dict[FlagType, str] = {
    FlagType.MISSING_EVIDENCE: "Missing Evidence",
    FlagType.UNSUPPORTED_CLAIM: "Unsupported Claim",
    FlagType.UNCHANGED_OUTPUT: "Unchanged Output",
    FlagType.LOW_CONFIDENCE: "Low Confidence",
    FlagType.DUPLICATE: "Duplicate",
    FlagType.INCONSISTENCY: "Inconsistency",
    FlagType.MALFORMED_OUTPUT: "Malformed Output",
    FlagType.EMPTY_CONTENT: "Empty Content",
}


def render(report: ValidationReport) -> None:
    """
    Render a ValidationReport as a structured Streamlit panel.

    Args:
        report: The validation report to display.
    """
    # --- Pass / fail banner ---
    if report.passed:
        st.success(
            "\u2705 **Validation passed** — no critical issues found. "
            "Content is ready for the approval gate (Slice 8)."
        )
    else:
        st.error(
            "\u274c **Validation failed** — critical issues must be resolved before approval. "
            "Review the flags below."
        )

    if not report.flags:
        st.caption("No validation flags — this artifact is clean.")
        return

    # --- Severity counts ---
    counts = {sev: 0 for sev in FlagSeverity}
    for f in report.flags:
        counts[f.severity] += 1

    col_crit, col_warn, col_info = st.columns(3)
    with col_crit:
        st.metric("Critical", counts[FlagSeverity.CRITICAL])
    with col_warn:
        st.metric("Warnings", counts[FlagSeverity.WARNING])
    with col_info:
        st.metric("Info", counts[FlagSeverity.INFO])

    st.divider()

    # --- Per-severity flag list ---
    for severity in (FlagSeverity.CRITICAL, FlagSeverity.WARNING, FlagSeverity.INFO):
        sev_flags = [f for f in report.flags if f.severity == severity]
        if not sev_flags:
            continue

        sev_label = _SEVERITY_LABEL[severity]
        st.markdown(f"**{sev_label} flags ({len(sev_flags)})**")

        for flag in sev_flags:
            type_label = _TYPE_LABEL.get(flag.flag_type, flag.flag_type.value)
            expander_title = f"[{type_label}] {flag.message[:90]}{'...' if len(flag.message) > 90 else ''}"
            # Critical flags are expanded by default; others are collapsed.
            expanded = severity == FlagSeverity.CRITICAL
            with st.expander(expander_title, expanded=expanded):
                st.caption(f"Location: `{flag.location}`")
                st.caption(f"Type: `{flag.flag_type.value}`  |  Severity: `{flag.severity.value}`")
                st.markdown(flag.message)
                if flag.evidence:
                    st.caption("**Evidence:**")
                    st.text(flag.evidence)

        st.write("")

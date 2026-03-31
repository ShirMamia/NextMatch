"""
Evidence panel — Streamlit component for displaying TailoredBullet source evidence.

Renders each tailored bullet alongside its verbatim source material, making the
grounding relationship explicit and user-reviewable before approval.

Each bullet shows:
  - The tailored text that would appear on the resume.
  - An expandable panel with the verbatim source bullet and section reference.
  - A confidence indicator; bullets with confidence=0.0 are flagged as unchanged.
"""
from __future__ import annotations

import streamlit as st

from app.schemas.tailoring import TailoredBullet


def render(bullets: list[TailoredBullet]) -> None:
    """Render a list of TailoredBullets with inline source evidence.

    Args:
        bullets: The tailored bullets to display. Each bullet's evidence
            attribute provides the verbatim source and confidence.
    """
    if not bullets:
        st.caption("No bullets generated for this section.")
        return

    for i, tb in enumerate(bullets, start=1):
        confidence_pct = int(tb.evidence.confidence * 100)
        if confidence_pct == 0:
            badge = "unchanged"
        else:
            badge = f"{confidence_pct}% confidence"

        st.markdown(f"- {tb.tailored}")
        with st.expander(f"Source evidence — bullet {i} ({badge})", expanded=False):
            st.caption("**Verbatim source (from CV):**")
            st.text(tb.evidence.source_bullet)
            st.caption(f"Section reference: `{tb.evidence.source_section}`")
            if tb.evidence.confidence < 0.5 and tb.evidence.confidence > 0.0:
                st.warning(
                    "Low confidence — this bullet may not be well tailored for this role."
                )
            elif tb.evidence.confidence == 0.0:
                st.info("This bullet was returned unchanged (no tailoring applied).")

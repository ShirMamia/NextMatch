"""
Candidate Profile page — Slice 2.

Flow:
  1. If a confirmed profile is in session state, show it with a replace option.
  2. Otherwise, let the user upload a file or paste text (mutually exclusive tabs).
  3. After input is provided, show a "Parse CV" button.
  4. After parsing succeeds, show the structured result for review.
  5. User explicitly clicks "Confirm profile" to write it into session state.

All parsing logic lives in app/parsers/cv_parser.py.
This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.parsers.cv_parser import parse_cv
from app.schemas.candidate import CandidateProfile
from app.services.llm_client import LLMParseError
from app.services.pdf_reader import PDFReadError, extract_text_from_bytes

# Session state keys used only within this page.
_KEY_PARSED = "profile_page__parsed_profile"       # CandidateProfile pending review
_KEY_RAW = "profile_page__raw_text"                # raw text that produced it


def render() -> None:
    st.header("Candidate Profile")

    confirmed: CandidateProfile | None = st.session_state.get("candidate_profile")

    # --- Step 1: show confirmed profile ---
    if confirmed is not None:
        _render_profile(confirmed)
        st.divider()
        if st.button("Replace profile", type="secondary"):
            st.session_state.candidate_profile = None
            st.session_state.pop(_KEY_PARSED, None)
            st.session_state.pop(_KEY_RAW, None)
            st.rerun()
        return

    # --- Step 2: show pending parsed result for review ---
    pending: CandidateProfile | None = st.session_state.get(_KEY_PARSED)
    if pending is not None:
        st.info("Review the parsed profile below. Confirm when ready.")
        _render_profile(pending)
        st.divider()
        col_confirm, col_cancel = st.columns([1, 1])
        with col_confirm:
            if st.button("Confirm profile", type="primary"):
                st.session_state.candidate_profile = pending
                st.session_state.pop(_KEY_PARSED, None)
                st.session_state.pop(_KEY_RAW, None)
                st.success(f"Profile confirmed for **{pending.name}**.")
                st.rerun()
        with col_cancel:
            if st.button("Re-upload / re-paste", type="secondary"):
                st.session_state.pop(_KEY_PARSED, None)
                st.session_state.pop(_KEY_RAW, None)
                st.rerun()
        return

    # --- Step 3: collect input from exactly one source ---
    st.subheader("Upload your CV")
    tab_upload, tab_paste = st.tabs(["Upload file", "Paste text"])

    raw_text: str | None = None
    source_label: str = ""

    with tab_upload:
        uploaded = st.file_uploader(
            "Upload a PDF or plain-text CV",
            type=["pdf", "txt"],
            label_visibility="collapsed",
        )
        if uploaded is not None:
            if uploaded.type == "application/pdf" or uploaded.name.endswith(".pdf"):
                try:
                    raw_text = extract_text_from_bytes(uploaded.read(), uploaded.name)
                    source_label = uploaded.name
                except PDFReadError as exc:
                    st.error(f"Could not extract text from PDF: {exc}")
                    raw_text = None
            else:
                raw_text = uploaded.read().decode("utf-8", errors="replace")
                source_label = uploaded.name

    with tab_paste:
        # Only accept pasted text if no file was already loaded in this render.
        if raw_text is None:
            pasted = st.text_area(
                "Paste your CV text here",
                height=300,
                label_visibility="collapsed",
                placeholder="Paste your full CV text here\u2026",
            )
            if pasted.strip():
                raw_text = pasted
                source_label = "pasted text"
        else:
            st.caption("A file is already loaded above. Switch to the Upload tab to change it.")

    if raw_text is not None:
        st.divider()
        with st.expander("Preview extracted text", expanded=False):
            st.text(raw_text[:3000] + ("\u2026" if len(raw_text) > 3000 else ""))

        if st.button("Parse CV", type="primary"):
            _run_parsing(raw_text, source_label)


def _run_parsing(raw_text: str, source_label: str) -> None:
    """Call the parser and store the result in page-scoped session state for review."""
    with st.spinner("Parsing CV\u2026"):
        try:
            profile = parse_cv(raw_text)
        except ValueError as exc:
            st.error(f"Cannot parse CV: {exc}")
            return
        except LLMParseError as exc:
            st.error(
                "The AI could not produce a structured result from your CV. "
                "Try again or check that the text is a real CV.\n\n"
                f"Detail: {exc}"
            )
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error during parsing: {exc}")
            return

    st.session_state[_KEY_PARSED] = profile
    st.session_state[_KEY_RAW] = raw_text
    st.rerun()


def _render_profile(profile: CandidateProfile) -> None:
    """Display a CandidateProfile for review or inspection."""
    st.subheader(profile.name)

    col1, col2 = st.columns(2)
    with col1:
        if profile.email:
            st.markdown(f"**Email:** {profile.email}")
        if profile.location:
            st.markdown(f"**Location:** {profile.location}")
    with col2:
        st.caption(f"Parsed at {profile.parsed_at.strftime('%Y-%m-%d %H:%M UTC')}")
        st.caption(f"ID: `{profile.candidate_id}`")

    if profile.summary:
        st.markdown("**Summary**")
        st.write(profile.summary)

    if profile.skills:
        st.markdown("**Skills**")
        st.write(", ".join(profile.skills))

    if profile.languages:
        st.markdown("**Languages**")
        st.write(", ".join(profile.languages))

    if profile.work_experience:
        st.markdown("**Work Experience**")
        for we in profile.work_experience:
            date_range = we.start_date or "?"
            if we.is_current:
                date_range += " \u2013 present"
            elif we.end_date:
                date_range += f" \u2013 {we.end_date}"
            with st.expander(f"{we.title} @ {we.company} ({date_range})"):
                for bullet in we.bullets:
                    st.markdown(f"- {bullet}")
                if we.skills_used:
                    st.caption("Skills: " + ", ".join(we.skills_used))

    if profile.education:
        st.markdown("**Education**")
        for ed in profile.education:
            year = f" ({ed.graduation_year})" if ed.graduation_year else ""
            st.markdown(f"- {ed.degree} in {ed.field}, {ed.institution}{year}")

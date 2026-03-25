"""
NextMatch - Streamlit entrypoint.

Initialises session state, configures logging, and renders the selected page.
All business logic lives outside this file; pages are thin UI shells.
"""
from __future__ import annotations

import streamlit as st

from app.ui.pages import (
    dashboard_page,
    discovery_page,
    profile_page,
    search_page,
    tailoring_page,
    tracker_page,
)
from app.utils.logging import configure_logging

st.set_page_config(
    page_title="NextMatch",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _init_logging() -> None:
    """Configure logging once per session.

    Shows a visible Streamlit error and stops the app on config failure.
    Does not fall back silently to INFO — config errors must be fixed.
    """
    if "logging_configured" in st.session_state:
        return
    try:
        from app.services.config import get_config
        cfg = get_config()
        configure_logging(cfg.log_level)
    except ValueError as exc:
        st.error(
            f"Configuration error: {exc}\n\n"
            "Fix the issue in your `.env` file and restart the app."
        )
        st.stop()
    st.session_state.logging_configured = True


def _init_session_state() -> None:
    """Initialise shared session state keys with safe, fresh defaults."""
    defaults_scalar = {
        "candidate_profile": None,
        "active_search_profile": None,
        "selected_job": None,
        "match_result": None,
        "tailored_resume": None,
        "validation_report": None,
    }
    defaults_list = ["search_profiles", "job_postings"]

    for key, value in defaults_scalar.items():
        if key not in st.session_state:
            st.session_state[key] = value

    for key in defaults_list:
        if key not in st.session_state:
            st.session_state[key] = []  # fresh list per session


_init_logging()
_init_session_state()

PAGES = {
    "Candidate Profile": profile_page,
    "Search Preferences": search_page,
    "Discover Jobs": discovery_page,
    "Tailoring Studio": tailoring_page,
    "Application Tracker": tracker_page,
    "Dashboard": dashboard_page,
}

with st.sidebar:
    st.title("NextMatch")
    st.caption("Evidence-grounded career copilot")
    st.divider()
    selected = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    profile_ok = st.session_state.get("candidate_profile") is not None
    jobs_ok = bool(st.session_state.get("job_postings"))
    resume_ok = st.session_state.get("tailored_resume") is not None
    st.markdown(
        ("OK" if profile_ok else "--") + " Profile loaded\n\n"
        + ("OK" if jobs_ok else "--") + " Jobs ingested\n\n"
        + ("OK" if resume_ok else "--") + " Resume tailored"
    )

PAGES[selected].render()

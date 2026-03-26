"""
Search Preferences page — Slice 3.

Allows the user to create one or more SearchProfile objects, select the active
search profile, and view saved profiles.

All schema construction is deterministic and form-based (no LLM used here).
Profiles are stored in st.session_state.search_profiles (list) and the currently
active profile in st.session_state.active_search_profile.

Active profile selection is keyed on search_id (not name) to be unambiguous
even if two profiles share the same name.

This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.schemas.search import LocationPreference, SearchProfile
from app.utils.ids import generate_id
from app.utils.time import format_datetime, utc_now


def _parse_csv(raw: str) -> list[str]:
    """Split a comma-separated string into a deduplicated, trimmed, non-empty list."""
    seen: set[str] = set()
    result: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def render() -> None:
    st.header("Search Preferences")

    profiles: list[SearchProfile] = st.session_state.get("search_profiles", [])
    active: SearchProfile | None = st.session_state.get("active_search_profile")

    # --- Active profile selector (keyed on search_id for unambiguous selection) ---
    if profiles:
        st.subheader("Active search profile")

        # Build a display label → search_id map. Labels include the name but selection
        # resolves through the ID so duplicate names remain unambiguous.
        id_to_profile = {p.search_id: p for p in profiles}
        ids = [p.search_id for p in profiles]
        labels = {p.search_id: p.name for p in profiles}

        active_id = active.search_id if active and active.search_id in id_to_profile else ids[0]

        selected_id = st.selectbox(
            "Select active profile",
            options=ids,
            format_func=lambda sid: labels[sid],
            index=ids.index(active_id),
            label_visibility="collapsed",
        )
        new_active = id_to_profile[selected_id]
        if active is None or new_active.search_id != active.search_id:
            st.session_state.active_search_profile = new_active

        st.divider()
        st.subheader("Saved profiles")
        for profile in profiles:
            marker = " \u2713 active" if active and profile.search_id == active.search_id else ""
            with st.expander(f"{profile.name}{marker}"):
                _render_profile_details(profile)
        st.divider()

    # --- Create new profile ---
    st.subheader("Create new search profile")
    with st.form("create_search_profile", clear_on_submit=True):
        name = st.text_input(
            "Profile name *",
            placeholder="e.g. Senior Backend Roles",
        )
        target_roles = st.text_input(
            "Target roles (comma-separated)",
            placeholder="e.g. Senior Backend Engineer, Staff Engineer",
        )
        required_skills = st.text_input(
            "Required skills (comma-separated)",
            placeholder="e.g. Python, REST API",
        )
        preferred_skills = st.text_input(
            "Preferred skills (comma-separated)",
            placeholder="e.g. Kafka, AWS, Docker",
        )
        excluded_keywords = st.text_input(
            "Excluded keywords (comma-separated)",
            placeholder="e.g. PHP, WordPress",
        )

        col_loc1, col_loc2, col_loc3 = st.columns(3)
        with col_loc1:
            city = st.text_input("City", placeholder="e.g. Tel Aviv")
        with col_loc2:
            country = st.text_input("Country", placeholder="e.g. Israel")
        with col_loc3:
            remote_ok_choice = st.selectbox(
                "Remote OK?",
                options=["Not specified", "Yes", "No"],
            )

        industry_preferences = st.text_input(
            "Industry preferences (comma-separated)",
            placeholder="e.g. SaaS, FinTech",
        )

        col_sen1, col_sen2 = st.columns(2)
        with col_sen1:
            min_seniority = st.text_input("Min seniority", placeholder="e.g. senior")
        with col_sen2:
            max_seniority = st.text_input("Max seniority", placeholder="e.g. staff")

        submitted = st.form_submit_button("Create profile", type="primary")

    if submitted:
        if not name.strip():
            st.error("Profile name is required.")
        else:
            remote_ok: bool | None = (
                True if remote_ok_choice == "Yes"
                else False if remote_ok_choice == "No"
                else None
            )
            profile = SearchProfile(
                search_id=generate_id(),
                name=name.strip(),
                target_roles=_parse_csv(target_roles),
                required_skills=_parse_csv(required_skills),
                preferred_skills=_parse_csv(preferred_skills),
                excluded_keywords=_parse_csv(excluded_keywords),
                location_preference=LocationPreference(
                    city=city.strip() or None,
                    country=country.strip() or None,
                    remote_ok=remote_ok,
                ),
                min_seniority=min_seniority.strip() or None,
                max_seniority=max_seniority.strip() or None,
                industry_preferences=_parse_csv(industry_preferences),
                created_at=utc_now(),
            )
            st.session_state.search_profiles.append(profile)
            if st.session_state.active_search_profile is None:
                st.session_state.active_search_profile = profile
            st.success(f"Profile **{profile.name}** created.")
            st.rerun()


def _render_profile_details(profile: SearchProfile) -> None:
    """Display SearchProfile details inside an expander."""
    if profile.target_roles:
        st.markdown(f"**Roles:** {', '.join(profile.target_roles)}")
    if profile.required_skills:
        st.markdown(f"**Required skills:** {', '.join(profile.required_skills)}")
    if profile.preferred_skills:
        st.markdown(f"**Preferred skills:** {', '.join(profile.preferred_skills)}")
    if profile.excluded_keywords:
        st.markdown(f"**Excluded:** {', '.join(profile.excluded_keywords)}")

    loc = profile.location_preference
    loc_parts: list[str] = []
    if loc.city:
        loc_parts.append(loc.city)
    if loc.country:
        loc_parts.append(loc.country)
    if loc.remote_ok is True:
        loc_parts.append("remote OK")
    elif loc.remote_ok is False:
        loc_parts.append("on-site only")
    if loc_parts:
        st.markdown(f"**Location:** {', '.join(loc_parts)}")

    if profile.min_seniority or profile.max_seniority:
        seniority = " \u2013 ".join(
            s for s in [profile.min_seniority, profile.max_seniority] if s
        )
        st.markdown(f"**Seniority:** {seniority}")
    if profile.industry_preferences:
        st.markdown(f"**Industries:** {', '.join(profile.industry_preferences)}")
    st.caption(
        f"Created {format_datetime(profile.created_at)} \u00b7 ID: `{profile.search_id}`"
    )

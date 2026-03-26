"""
Discover Jobs page — Slice 3.

Allows the user to ingest job descriptions (PDF/TXT upload or pasted text),
parse them into JobPosting, check for duplicates, and add them to the session.
Ingested jobs can be browsed and one selected for downstream processing.

Ranking is NOT implemented in this slice — jobs are shown in ingestion order.
All parsing logic lives in app/parsers/job_parser.py.
Deduplication logic lives in app/discovery/deduper.py.
This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.discovery.deduper import is_duplicate
from app.parsers.job_parser import parse_job
from app.schemas.job import JobPosting, JobSource
from app.services.llm_client import LLMParseError
from app.services.pdf_reader import PDFReadError, extract_text_from_bytes
from app.utils.time import format_datetime


def render() -> None:
    st.header("Discover Jobs")
    st.caption("Jobs are listed in ingestion order. Ranking comes in Slice 4.")

    active_profile = st.session_state.get("active_search_profile")
    if active_profile is None:
        st.info(
            "No active search profile. "
            "Go to **Search Preferences** to create one before ingesting jobs."
        )

    tab_ingest, tab_list = st.tabs(["Ingest Job", "Job List"])

    with tab_ingest:
        _render_ingest_tab()

    with tab_list:
        _render_job_list_tab()


# ---------------------------------------------------------------------------
# Ingest tab
# ---------------------------------------------------------------------------

def _render_ingest_tab() -> None:
    st.subheader("Add a job posting")
    tab_upload, tab_paste = st.tabs(["Upload file", "Paste text"])

    raw_text: str | None = None
    # source_type and source_name reflect the actual ingestion method.
    source_type: str = "manual"
    source_name: str = "manual"

    with tab_upload:
        uploaded = st.file_uploader(
            "Upload a PDF or plain-text job description",
            type=["pdf", "txt"],
            label_visibility="collapsed",
        )
        if uploaded is not None:
            if uploaded.type == "application/pdf" or uploaded.name.endswith(".pdf"):
                try:
                    raw_text = extract_text_from_bytes(uploaded.read(), uploaded.name)
                except PDFReadError as exc:
                    st.error(f"Could not extract text from PDF: {exc}")
                    raw_text = None
            else:
                raw_text = uploaded.read().decode("utf-8", errors="replace")

            if raw_text is not None:
                # Uploaded file — use "saved" to reflect that the text came from a file.
                source_type = "saved"
                source_name = uploaded.name

    with tab_paste:
        if raw_text is None:
            pasted = st.text_area(
                "Paste job description text here",
                height=300,
                label_visibility="collapsed",
                placeholder="Paste the full job description here\u2026",
            )
            if pasted.strip():
                raw_text = pasted
                source_type = "manual"
                source_name = "manual"
        else:
            st.caption("A file is already loaded. Switch to the Upload tab to change it.")

    if raw_text is not None:
        st.divider()
        with st.expander("Preview extracted text", expanded=False):
            st.text(raw_text[:3000] + ("\u2026" if len(raw_text) > 3000 else ""))

        if st.button("Parse and add job", type="primary"):
            _run_ingestion(raw_text, source_type, source_name)


def _run_ingestion(raw_text: str, source_type: str, source_name: str) -> None:
    """Parse the raw text into a JobPosting, check for duplicates, and add to session state."""
    source = JobSource(
        source_type=source_type,  # type: ignore[arg-type]
        source_name=source_name,
    )

    with st.spinner("Parsing job description\u2026"):
        try:
            job = parse_job(raw_text, source)
        except ValueError as exc:
            st.error(f"Cannot parse job: {exc}")
            return
        except LLMParseError as exc:
            st.error(
                "The AI could not produce a structured result from this job description. "
                "Try again or check that the text is a real job posting.\n\n"
                f"Detail: {exc}"
            )
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error during parsing: {exc}")
            return

    existing: list[JobPosting] = st.session_state.get("job_postings", [])
    if is_duplicate(job, existing):
        st.warning(
            f"**{job.title}** at **{job.company}** already exists in your job list. "
            "Duplicate not added."
        )
        return

    st.session_state.job_postings.append(job)
    st.session_state.selected_job = job
    st.success(f"Added: **{job.title}** at **{job.company}**")
    st.rerun()


# ---------------------------------------------------------------------------
# Job list tab
# ---------------------------------------------------------------------------

def _render_job_list_tab() -> None:
    jobs: list[JobPosting] = st.session_state.get("job_postings", [])

    if not jobs:
        st.info("No jobs ingested yet. Use the Ingest Job tab to add job descriptions.")
        return

    st.subheader(f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} ingested")

    selected_job: JobPosting | None = st.session_state.get("selected_job")
    id_to_job: dict[str, JobPosting] = {j.job_id: j for j in jobs}
    job_ids = [j.job_id for j in jobs]

    # Determine current selection by job_id — stable even if labels repeat.
    current_id = selected_job.job_id if selected_job and selected_job.job_id in id_to_job else job_ids[0]

    chosen_id = st.radio(
        "Select a job to view details",
        options=job_ids,
        index=job_ids.index(current_id),
        format_func=lambda jid: f"{id_to_job[jid].title} \u2014 {id_to_job[jid].company}",
        label_visibility="collapsed",
    )

    chosen_job = id_to_job[chosen_id]
    if selected_job is None or chosen_job.job_id != selected_job.job_id:
        st.session_state.selected_job = chosen_job

    st.divider()
    _render_job_detail(chosen_job)


def _render_job_detail(job: JobPosting) -> None:
    """Display the details of a selected JobPosting."""
    st.subheader(job.title)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Company:** {job.company}")
        if job.location:
            st.markdown(f"**Location:** {job.location}")
        if job.is_remote is True:
            st.markdown("**Remote:** Yes")
        elif job.is_remote is False:
            st.markdown("**Remote:** No (on-site)")
    with col2:
        if job.seniority_level:
            st.markdown(f"**Seniority:** {job.seniority_level}")
        if job.employment_type:
            st.markdown(f"**Employment:** {job.employment_type}")
        st.caption(f"Ingested {format_datetime(job.source.ingested_at)}")
        st.caption(f"ID: `{job.job_id}`")

    required = [r for r in job.requirements if r.is_required]
    preferred = [r for r in job.requirements if not r.is_required]

    if required:
        st.markdown("**Required**")
        for req in required:
            tags = f" `{'` `'.join(req.skill_tags)}`" if req.skill_tags else ""
            st.markdown(f"- {req.text}{tags}")

    if preferred:
        st.markdown("**Preferred / nice to have**")
        for req in preferred:
            tags = f" `{'` `'.join(req.skill_tags)}`" if req.skill_tags else ""
            st.markdown(f"- {req.text}{tags}")

    with st.expander("Raw job description", expanded=False):
        st.text(
            job.description_raw[:3000] + ("\u2026" if len(job.description_raw) > 3000 else "")
        )

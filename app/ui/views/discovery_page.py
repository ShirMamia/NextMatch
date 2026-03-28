"""
Discover Jobs page — Slice 4.

Allows the user to ingest job descriptions (PDF/TXT upload or pasted text),
parse them into JobPosting, check for duplicates, and add them to the session.
When an active search profile exists, jobs are ranked by search profile fit.
Without an active profile, jobs are shown in ingestion order.

Ranking scores represent SEARCH PROFILE FIT only — how well the job matches what
the user says they are looking for. Candidate-job fit (Slice 5) is separate.

All parsing logic lives in app/parsers/job_parser.py.
Deduplication logic lives in app/discovery/deduper.py.
Ranking logic lives in app/discovery/job_ranker.py.
This file is a thin UI shell only.
"""
from __future__ import annotations

import streamlit as st

from app.discovery.deduper import is_duplicate
from app.discovery.job_ranker import JobRankResult, rank_jobs
from app.parsers.job_parser import parse_job
from app.schemas.job import JobPosting, JobSource
from app.schemas.search import SearchProfile
from app.services.llm_client import LLMParseError
from app.services.pdf_reader import PDFReadError, extract_text_from_bytes
from app.utils.time import format_datetime


def render() -> None:
    st.header("Discover Jobs")

    active_profile: SearchProfile | None = st.session_state.get("active_search_profile")
    if active_profile is None:
        st.info(
            "No active search profile. "
            "Go to **Search Preferences** to create one before ingesting jobs."
        )
    else:
        st.caption(
            f"Ranking by search profile fit — **{active_profile.name}**. "
            "This score reflects how well a job matches your search criteria, "
            "not your candidacy."
        )

    tab_ingest, tab_list = st.tabs(["Ingest Job", "Job List"])

    with tab_ingest:
        _render_ingest_tab()

    with tab_list:
        _render_job_list_tab(active_profile)


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

def _render_job_list_tab(active_profile: SearchProfile | None) -> None:
    jobs: list[JobPosting] = st.session_state.get("job_postings", [])

    if not jobs:
        st.info("No jobs ingested yet. Use the Ingest Job tab to add job descriptions.")
        return

    # Rank jobs when an active profile exists; otherwise keep ingestion order.
    if active_profile is not None:
        ranked: list[JobRankResult] = rank_jobs(jobs, active_profile)
        ordered_jobs = [r.job for r in ranked]
        score_by_id: dict[str, float] = {r.job.job_id: r.total_score for r in ranked}
        breakdown_by_id: dict[str, JobRankResult] = {r.job.job_id: r for r in ranked}
    else:
        ordered_jobs = jobs
        score_by_id = {}
        breakdown_by_id = {}

    st.subheader(f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} ingested")
    if active_profile:
        st.caption(
            "Sorted by search profile fit (highest first). "
            "Score shown is profile fit only \u2014 not your suitability for the role."
        )
    else:
        st.caption("Jobs shown in ingestion order. Set an active search profile to enable ranking.")

    selected_job: JobPosting | None = st.session_state.get("selected_job")
    id_to_job: dict[str, JobPosting] = {j.job_id: j for j in ordered_jobs}
    job_ids = [j.job_id for j in ordered_jobs]

    # Determine current selection by job_id — stable even if labels repeat.
    current_id = (
        selected_job.job_id
        if selected_job and selected_job.job_id in id_to_job
        else job_ids[0]
    )

    def _radio_label(jid: str) -> str:
        job = id_to_job[jid]
        label = f"{job.title} \u2014 {job.company}"
        if jid in score_by_id:
            pct = int(score_by_id[jid] * 100)
            label = f"{pct}% \u2014 {label}"
        return label

    chosen_id = st.radio(
        "Select a job to view details",
        options=job_ids,
        index=job_ids.index(current_id),
        format_func=_radio_label,
        label_visibility="collapsed",
    )

    chosen_job = id_to_job[chosen_id]
    if selected_job is None or chosen_job.job_id != selected_job.job_id:
        st.session_state.selected_job = chosen_job

    st.divider()
    _render_job_detail(chosen_job, breakdown_by_id.get(chosen_id))


def _render_job_detail(job: JobPosting, rank_result: JobRankResult | None) -> None:
    """Display the details of a selected JobPosting, including ranking breakdown if available."""
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

    # --- Search profile fit breakdown ---
    if rank_result is not None:
        st.divider()
        _render_rank_breakdown(rank_result)

    with st.expander("Raw job description", expanded=False):
        st.text(
            job.description_raw[:3000] + ("\u2026" if len(job.description_raw) > 3000 else "")
        )


def _render_rank_breakdown(rank_result: JobRankResult) -> None:
    """Display the search profile fit score and per-factor breakdown."""
    total_pct = int(rank_result.total_score * 100)

    st.markdown(f"**Search profile fit: {total_pct}%**")
    if rank_result.excluded_keyword_hit:
        st.warning("Excluded keyword detected \u2014 score penalised by 50%.")

    st.caption(
        "This score reflects how well the job matches your search criteria. "
        "It is not a measure of your suitability for the role."
    )

    with st.expander("Score breakdown", expanded=False):
        for factor in rank_result.factors:
            factor_pct = int(factor.score * 100) if factor.weight > 0 else 0
            weight_pct = int(factor.weight * 100)
            col_name, col_score = st.columns([3, 1])
            with col_name:
                label = factor.name.replace("_", " ").title()
                st.markdown(f"**{label}** (weight {weight_pct}%)")
                for reason in factor.reasons:
                    st.caption(f"\u2013 {reason}")
            with col_score:
                if factor.weight > 0:
                    st.metric(label="score", value=f"{factor_pct}%", label_visibility="collapsed")

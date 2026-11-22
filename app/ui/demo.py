"""Fictional inputs for the Streamlit demo, loaded in memory only."""
from __future__ import annotations

from app.schemas.candidate import CandidateProfile, WorkExperience
from app.schemas.job import JobPosting, JobRequirement, JobSource


def sample_inputs() -> tuple[CandidateProfile, list[JobPosting]]:
    experience = WorkExperience(
        company="Example Analytics Lab",
        title="Data Analyst",
        start_date="2023-06",
        is_current=True,
        bullets=[
            "Built Python and SQL validation checks for weekly inventory reports.",
            "Published Power BI dashboards and documented metric definitions.",
        ],
        skills_used=["Python", "SQL", "Power BI"],
    )
    profile = CandidateProfile(
        candidate_id="sample-candidate",
        name="Alex Example",
        summary="Data analyst focused on reliable reporting and explainable metrics.",
        skills=["Python", "SQL", "Power BI"],
        work_experience=[experience],
        raw_text="\n".join(
            ["Alex Example — Data Analyst, Example Analytics Lab", *experience.bullets]
        ),
    )
    jobs = [
        JobPosting(
            job_id="sample-analytics-role",
            title="BI Analyst",
            company="Sample Harbor Studio",
            description_raw="Build Power BI dashboards and validate reporting data with SQL. Python is preferred.",
            requirements=[
                JobRequirement(text="Validate reporting data with SQL", skill_tags=["SQL"]),
                JobRequirement(text="Build dashboards with Power BI", skill_tags=["Power BI"]),
                JobRequirement(
                    text="Use Python for automation", is_required=False, skill_tags=["Python"]
                ),
            ],
            source=JobSource(source_type="saved", source_name="Fictional portfolio sample"),
        ),
        JobPosting(
            job_id="sample-data-engineering-role",
            title="Data Engineer",
            company="Sample Harbor Studio",
            description_raw="Build SQL pipelines and orchestrate workflows with Airflow.",
            requirements=[
                JobRequirement(text="Build SQL pipelines", skill_tags=["SQL"]),
                JobRequirement(text="Orchestrate workflows with Airflow", skill_tags=["Airflow"]),
            ],
            source=JobSource(source_type="saved", source_name="Fictional portfolio sample"),
        ),
    ]
    return profile, jobs

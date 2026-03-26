"""
Deduper — deterministic deduplication for ingested job postings.

A job is considered a duplicate if its normalized title+company key matches
an existing posting in the list. Normalization strips all non-alphanumeric
characters and lowercases the result before comparison.

Design decisions:
  - Exact match on the normalized key. No fuzzy or semantic matching in Slice 3.
  - Title alone is not sufficient for dedup (the same company may post different roles).
  - Company alone is not sufficient (many companies can share a title like "Engineer").
  - The combination is practical and explainable for Slice 3.
"""
from __future__ import annotations

import re

from app.schemas.job import JobPosting


def _dedup_key(title: str, company: str) -> str:
    """Compute a normalized deduplication key from title and company.

    Lowercases both strings and removes all non-alphanumeric characters before
    concatenating with a separator. This makes the key robust to punctuation and
    minor capitalization differences (e.g. "Sr." vs "sr", "Acme Corp." vs "Acme Corp").

    Args:
        title: Job posting title.
        company: Hiring company name.

    Returns:
        A normalized string suitable for exact-match deduplication.
    """
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    return _norm(title) + "|" + _norm(company)


def is_duplicate(job: JobPosting, existing_jobs: list[JobPosting]) -> bool:
    """Return True if a job with the same normalized title+company already exists.

    Args:
        job: The candidate job posting to check.
        existing_jobs: The list of already-ingested job postings.

    Returns:
        True if a duplicate is detected, False otherwise.
    """
    key = _dedup_key(job.title, job.company)
    return any(_dedup_key(j.title, j.company) == key for j in existing_jobs)

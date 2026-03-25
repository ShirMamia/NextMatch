"""
Discover Jobs page — Slice 1 stub.

Full implementation arrives in Slice 3 (job ingestion, normalisation, deduplication)
and Slice 4 (ranking).
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.header("Discover Jobs")
    st.info("Ingest and browse ranked job postings here. (Coming in Slices 3 and 4)")

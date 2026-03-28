"""
Tailoring Studio page — Slice 1 stub.

Full implementation spans Slices 5 (matching), 6 (generation), and 7 (validation).
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.header("Tailoring Studio")
    st.info(
        "Select a job to see your match analysis, generate a tailored resume, "
        "review validation flags, and approve before saving. (Coming in Slices 5-7)"
    )

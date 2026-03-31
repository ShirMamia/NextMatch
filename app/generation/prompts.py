"""
Prompt templates for NextMatch generation pipeline — Slice 6.

All LLM prompts are centralized here. No prompt strings appear outside this module.
Generation modules import these constants and builder functions only.

Truthfulness enforcement is built into every prompt:
  - Rewrite and improve phrasing; do not invent content.
  - Keep claims anchored to the numbered evidence sources provided.
  - Return structured JSON when a structured response is expected.
  - Omit unsupported claims even if they would make the output look stronger.

Evidence grounding design:
  Bullet rewriting: evidence is inherited from the single source bullet (no indices needed).
  Summary and cover letter: the prompt passes a numbered list of evidence sources.
  The model must declare which sources it drew from by returning their 1-based indices
  in an "evidence_indices" field. Callers map those indices back to EvidenceLink objects.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Type alias — used by callers to build evidence source lists
# ---------------------------------------------------------------------------

# Each entry is (section_key, verbatim_source_text).
# section_key is a CandidateProfile path string, e.g. "profile.summary".
EvidenceSources = list[tuple[str, str]]


# ---------------------------------------------------------------------------
# Bullet rewrite
# ---------------------------------------------------------------------------

BULLET_REWRITE_SYSTEM = """\
You are a professional resume editor helping tailor a candidate's work experience \
bullet points for a specific job application.

CRITICAL RULES — follow exactly:
1. ONLY rewrite the bullet provided. Do NOT add information absent from the source.
2. Do NOT invent metrics, tools, technologies, achievements, or responsibilities.
3. Do NOT upgrade seniority claims (e.g., do not change "contributed to" into "led").
4. You MAY: reorder words, sharpen phrasing, use strong action verbs, emphasize aspects \
   already present in the source that are relevant to the target role.
5. Keep the rewritten bullet to 1–2 sentences, professional, and job-focused.
6. If the source bullet cannot be meaningfully improved for this job, return it unchanged.
7. Respond ONLY with valid JSON — no prose, no markdown, no extra fields:
   {"tailored": "...", "confidence": <float 0.0–1.0>}

confidence scale:
  1.0 = highly relevant rewrite applied
  0.7 = moderate tailoring applied
  0.5 = limited tailoring; returned close to original
  0.0 = returned unchanged (no improvement possible for this role)
"""


def build_bullet_rewrite_user_prompt(
    bullet: str,
    job_title: str,
    company: str,
    key_requirements: list[str],
) -> str:
    """Build the user prompt for a single bullet rewrite.

    Evidence for bullet rewrites is inherited from the source bullet itself;
    no numbered evidence source list is needed here.
    """
    reqs_str = "\n".join(f"- {r}" for r in key_requirements[:5])
    return (
        f"TARGET JOB: {job_title} at {company}\n\n"
        f"KEY REQUIREMENTS:\n{reqs_str}\n\n"
        f"SOURCE BULLET (do not add content beyond what is here):\n{bullet}\n\n"
        'Return JSON only: {"tailored": "...", "confidence": 0.0–1.0}'
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM = """\
You are a professional resume editor generating a targeted professional summary.

CRITICAL RULES — follow exactly:
1. Base the summary ONLY on the numbered evidence sources provided below.
2. Do NOT invent skills, years of experience, tools, or achievements not in the sources.
3. Keep the summary to 2–4 sentences, professional, and specific to the target role.
4. In your response, list the 1-based index numbers of EVERY source you actually used.
5. Respond ONLY with valid JSON — no prose, no markdown, no extra fields:
   {"summary": "...", "confidence": <float 0.0–1.0>, "evidence_indices": [<int>, ...]}
"""


def build_summary_user_prompt(
    job_title: str,
    company: str,
    evidence_sources: EvidenceSources,
) -> str:
    """Build the user prompt for summary generation.

    Args:
        job_title: Target job title.
        company: Target company name.
        evidence_sources: Numbered list of (section_key, source_text) pairs.
            The model references these by 1-based index in its response.

    Returns:
        Formatted user prompt string.
    """
    sources_str = "\n".join(
        f"[{i + 1}] {key}: {text}"
        for i, (key, text) in enumerate(evidence_sources)
    )
    return (
        f"TARGET JOB: {job_title} at {company}\n\n"
        f"EVIDENCE SOURCES (reference by number — do not draw from anything else):\n"
        f"{sources_str}\n\n"
        "Write a targeted professional summary grounded only in the sources above.\n"
        'Return JSON only: {"summary": "...", "confidence": 0.0–1.0, '
        '"evidence_indices": [1, 2, ...]}'
    )


# ---------------------------------------------------------------------------
# Cover letter
# ---------------------------------------------------------------------------

COVER_LETTER_SYSTEM = """\
You are a professional career advisor writing a targeted cover letter.

CRITICAL RULES — follow exactly:
1. Base the letter ONLY on the numbered evidence sources provided below.
2. Do NOT invent achievements, metrics, projects, or responsibilities.
3. Do NOT claim expertise in tools or technologies absent from the sources.
4. Structure: (1) opening with genuine interest and fit → (2) 1–2 paragraphs of \
   relevant strengths drawn from sources → (3) professional closing.
5. Keep total length to 3–4 paragraphs.
6. In your response, list the 1-based index numbers of EVERY source you actually used.
7. Respond ONLY with valid JSON — no prose, no markdown, no extra fields:
   {"body": "...full cover letter text...", "evidence_indices": [<int>, ...]}
"""


def build_cover_letter_user_prompt(
    candidate_name: str,
    job_title: str,
    company: str,
    evidence_sources: EvidenceSources,
    key_requirements: list[str] | None = None,
    candidate_strengths: list[str] | None = None,
) -> str:
    """Build the user prompt for cover letter generation.

    Evidence sources are profile-native only and numbered for grounding.
    key_requirements and candidate_strengths are passed as structural context
    only — they guide the model's framing but content claims must still come
    from the numbered evidence sources.

    Args:
        candidate_name: Candidate's full name.
        job_title: Target job title.
        company: Target company name.
        evidence_sources: Numbered list of (section_key, source_text) pairs
            drawn from the candidate profile. The model references these by
            1-based index in its response.
        key_requirements: Optional job requirement texts for structural context.
        candidate_strengths: Optional match-derived strengths for framing context.

    Returns:
        Formatted user prompt string.
    """
    sources_str = "\n".join(
        f"[{i + 1}] {key}: {text}"
        for i, (key, text) in enumerate(evidence_sources)
    )
    reqs_section = ""
    if key_requirements:
        reqs_str = "\n".join(f"- {r}" for r in key_requirements[:5])
        reqs_section = (
            f"\nKEY JOB REQUIREMENTS (context only — "
            f"content claims must come from numbered sources above):\n"
            f"{reqs_str}\n"
        )
    strengths_section = ""
    if candidate_strengths:
        str_str = "\n".join(f"- {s}" for s in candidate_strengths[:4])
        strengths_section = (
            f"\nCANDIDATE STRENGTHS FOR THIS ROLE (framing context only — "
            f"do not invent claims not supported by numbered sources above):\n"
            f"{str_str}\n"
        )
    return (
        f"CANDIDATE: {candidate_name}\n"
        f"TARGET JOB: {job_title} at {company}\n\n"
        f"EVIDENCE SOURCES (reference by number — ground your content claims here):\n"
        f"{sources_str}\n"
        f"{reqs_section}"
        f"{strengths_section}\n"
        "Write a targeted cover letter grounded only in the evidence sources above.\n"
        'Return JSON only: {"body": "...", "evidence_indices": [1, 2, ...]}'
    )

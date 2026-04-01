"""
Deterministic claim checker — Slice 7.

Compares a tailored bullet against its source evidence to detect potentially
unsupported claims. All checks are deterministic and heuristic — not semantic
proof of truth. The goal is to surface clear signals, not to achieve certainty.

Conservative design principles:
  - Prefer warnings over false-critical flags.
  - Only raise CRITICAL flags when evidence is structurally absent.
  - Flag specific suspicious terms, not whole bullets, where possible.
  - Avoid false positives from legitimate paraphrasing.

Checks performed per bullet:
  1. Token overlap  — low overlap between tailored and source key terms → WARNING
  2. Unsupported numbers / metrics — digit/percentage in tailored not in source → WARNING
  3. Seniority upgrade terms — "led", "managed", "owned" etc. not in source → WARNING
  4. Unsupported technology names — capitalized proper nouns not in source → WARNING

All checks return a list of ValidationFlag objects ready for inclusion in a
ValidationReport. An empty list means no issues were detected.
"""
from __future__ import annotations

import re

from app.schemas.validation import FlagSeverity, FlagType, ValidationFlag
from app.utils.ids import generate_id


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common English words excluded from key-term comparison to reduce noise.
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "to", "of", "in",
    "on", "at", "by", "for", "with", "and", "or", "but", "not", "no",
    "so", "as", "it", "its", "this", "that", "their", "they", "we", "our",
    "my", "your", "his", "her", "from", "into", "through", "during", "when",
    "where", "who", "which", "what", "how", "than", "also", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "own", "up",
    "out", "then", "once", "use", "used", "using",
})

# Token overlap threshold: if fewer than this fraction of the tailored bullet's
# key tokens appear in the source bullet, the grounding is considered weak.
_OVERLAP_WARNING_THRESHOLD = 0.4

# Seniority / leadership terms that represent a meaningful claim upgrade.
# If any of these appear in the tailored text but not in the source, a warning
# is raised. Only whole-word matches are checked (via regex word boundaries).
_SENIORITY_TERMS: frozenset[str] = frozenset({
    "led", "lead", "leads", "managed", "manage", "manages", "directed",
    "owned", "owns", "spearheaded", "headed", "oversaw", "supervised",
    "architected", "established", "drove", "drive", "drives",
})

# Common resume sentence-starting verbs that are capitalized at the beginning of
# a bullet but are NOT technology or proper-noun names. These are excluded from
# the tech-name detection pass to avoid false positives from legitimate paraphrases
# such as "Built ..." → "Developed ..." or "Engineered ...".
_COMMON_SENTENCE_STARTERS: frozenset[str] = frozenset({
    "built", "developed", "designed", "implemented", "created", "established",
    "managed", "led", "engineered", "architected", "delivered", "maintained",
    "improved", "optimized", "reduced", "increased", "automated", "migrated",
    "integrated", "deployed", "configured", "coordinated", "collaborated",
    "supported", "helped", "worked", "ensured", "analyzed", "researched",
    "written", "wrote", "contributed", "participated", "handled", "provided",
    "performed", "executed", "initiated", "launched", "introduced", "trained",
    "mentored", "coached", "reviewed", "tested", "validated", "monitored",
    "tracked", "reported", "presented", "documented", "communicated",
    "structured", "streamlined", "transformed", "updated", "refactored",
    "shipped", "scaled", "owned", "spearheaded", "drove", "oversaw",
    "supervised", "directed", "planned", "scheduled", "prioritized",
    "identified", "resolved", "fixed", "debugged", "assessed", "evaluated",
    "leveraged", "utilized", "applied", "enabled", "facilitated",
    "grew", "generated", "achieved", "met", "exceeded", "completed",
    "finished", "produced", "organized", "prepared", "learned", "acquired",
    # Common adjectives / qualifiers that may appear capitalized in bullets
    "responsible", "experienced", "skilled", "proficient", "passionate",
    "strong", "proven", "demonstrated", "successful", "effective",
    # Titles and seniority qualifiers
    "senior", "junior", "principal", "staff", "lead",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key_tokens(text: str) -> frozenset[str]:
    """Return a set of meaningful tokens: lowercase, 3+ chars, non-stop-word."""
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    return frozenset(
        t for t in normalized.split()
        if len(t) >= 3 and t not in _STOP_WORDS
    )


def _extract_numbers(text: str) -> set[str]:
    """
    Extract numeric values and percentages from text.

    Matches integers (e.g. 20), decimals (e.g. 20.5), percentages (e.g. 20%),
    and decimal percentages (e.g. 20.5%).

    The trailing \\b is intentionally omitted after the optional % because %
    is a non-word character — including \\b after it would cause the match to
    fail whenever % is the terminal character.
    """
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?", text))


def _extract_tech_terms(text: str) -> set[str]:
    """
    Extract capitalized words that look like technology or proper-noun names.

    Matches words that begin with an uppercase letter followed by at least one
    lowercase letter (e.g. 'Kafka', 'FastAPI', 'PostgreSQL'). Common
    sentence-starting verbs and qualifiers (e.g. 'Built', 'Developed',
    'Engineered') are explicitly excluded via _COMMON_SENTENCE_STARTERS to
    avoid flagging legitimate paraphrases as unsupported tech claims.
    """
    candidates = set(re.findall(r"\b[A-Z][a-z][a-zA-Z0-9]*\b", text))
    return {t for t in candidates if t.lower() not in _COMMON_SENTENCE_STARTERS}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_bullet(
    tailored: str,
    source_bullet: str,
    location: str,
) -> list[ValidationFlag]:
    """
    Check a single tailored bullet against its source evidence for unsupported claims.

    Args:
        tailored: The rewritten bullet text.
        source_bullet: The verbatim source bullet the tailored text was derived from.
        location: A path string identifying the bullet within the resume, used
            as the ValidationFlag.location value.

    Returns:
        A list of ValidationFlag objects. Empty list means no issues detected.
    """
    flags: list[ValidationFlag] = []

    tailored_key = _key_tokens(tailored)
    source_key = _key_tokens(source_bullet)

    # --- 1. Token overlap ---
    if tailored_key:
        overlap = len(tailored_key & source_key) / len(tailored_key)
        if overlap < _OVERLAP_WARNING_THRESHOLD:
            flags.append(ValidationFlag(
                flag_id=generate_id(),
                severity=FlagSeverity.WARNING,
                flag_type=FlagType.UNSUPPORTED_CLAIM,
                message=(
                    f"Low key-term overlap ({int(overlap * 100)}%) between the tailored bullet "
                    "and its source evidence — the rewrite may introduce unsupported content."
                ),
                location=location,
                evidence=f"Tailored: {tailored!r}  |  Source: {source_bullet!r}",
            ))

    # --- 2. Unsupported numbers / metrics ---
    tailored_nums = _extract_numbers(tailored)
    source_nums = _extract_numbers(source_bullet)
    unsupported_nums = tailored_nums - source_nums
    for num in sorted(unsupported_nums):
        flags.append(ValidationFlag(
            flag_id=generate_id(),
            severity=FlagSeverity.WARNING,
            flag_type=FlagType.UNSUPPORTED_CLAIM,
            message=(
                f"Metric or number {num!r} appears in the tailored bullet "
                "but is not present in the source evidence."
            ),
            location=location,
            evidence=f"Tailored: {tailored!r}  |  Source: {source_bullet!r}",
        ))

    # --- 3. Seniority upgrade terms ---
    tailored_words = set(re.findall(r"\b\w+\b", tailored.lower()))
    source_words = set(re.findall(r"\b\w+\b", source_bullet.lower()))
    unsupported_seniority = _SENIORITY_TERMS & (tailored_words - source_words)
    for term in sorted(unsupported_seniority):
        flags.append(ValidationFlag(
            flag_id=generate_id(),
            severity=FlagSeverity.WARNING,
            flag_type=FlagType.UNSUPPORTED_CLAIM,
            message=(
                f"Leadership/seniority term {term!r} appears in the tailored bullet "
                "but is not present in the source evidence — this may be a claim upgrade."
            ),
            location=location,
            evidence=f"Tailored: {tailored!r}  |  Source: {source_bullet!r}",
        ))

    # --- 4. Unsupported technology / tool names ---
    tailored_tech = _extract_tech_terms(tailored)
    source_tech_lower = {t.lower() for t in _extract_tech_terms(source_bullet)}
    unsupported_tech = sorted(t for t in tailored_tech if t.lower() not in source_tech_lower)
    for term in unsupported_tech:
        flags.append(ValidationFlag(
            flag_id=generate_id(),
            severity=FlagSeverity.WARNING,
            flag_type=FlagType.UNSUPPORTED_CLAIM,
            message=(
                f"Technology or proper noun {term!r} appears in the tailored bullet "
                "but is not present in the source evidence."
            ),
            location=location,
            evidence=f"Source: {source_bullet!r}",
        ))

    return flags

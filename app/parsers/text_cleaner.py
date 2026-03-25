"""
Text cleaner — deterministic preprocessing for raw CV text.

Normalizes whitespace, strips common noise patterns, and returns clean
text ready for LLM parsing. Does not interpret content — that is cv_parser's job.
"""
from __future__ import annotations

import re


def clean_cv_text(raw: str) -> str:
    """Clean raw CV text for LLM parsing.

    Applies normalization in this order:
      1. Normalize line endings to \\n.
      2. Strip HTML tags (common in copy-paste from job sites or web CVs).
      3. Collapse runs of horizontal whitespace within lines.
      4. Collapse runs of more than two consecutive blank lines.
      5. Strip leading/trailing whitespace from each line.
      6. Strip leading/trailing whitespace from the whole text.

    Args:
        raw: Raw CV text, as extracted from PDF or typed/pasted by user.

    Returns:
        Cleaned text string. Returns empty string if input is empty or whitespace.
    """
    if not raw or not raw.strip():
        return ""

    text = raw

    # 1. Normalize line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Strip HTML tags.
    text = re.sub(r"<[^>]+>", " ", text)

    # 3. Collapse horizontal whitespace within each line (tabs → space, multiple spaces → one).
    text = re.sub(r"[ \t]+", " ", text)

    # 4. Strip leading/trailing whitespace from each line.
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    # 5. Collapse runs of more than two consecutive blank lines to exactly two.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

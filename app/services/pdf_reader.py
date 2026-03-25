"""
PDF reader — extracts raw text from a PDF file.

This is infrastructure only. It extracts text and returns a clean string.
Domain logic (parsing, cleaning, structuring) belongs in parsers/.

pdfplumber is used because it handles multi-column layouts and preserves
reading order better than PyPDF2 for typical CV documents.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PDFReadError(Exception):
    """Raised when a PDF cannot be read or yields no usable text."""


def extract_text_from_pdf(path: Path) -> str:
    """Extract raw text from a PDF file.

    Concatenates text from all pages, separated by newlines.
    Strips leading/trailing whitespace from the result.

    Args:
        path: Absolute or relative path to the PDF file.

    Returns:
        Raw text content of the PDF as a single string.

    Raises:
        PDFReadError: if the file does not exist, cannot be opened,
                      or yields no extractable text.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise PDFReadError(
            "pdfplumber is not installed. Add it to requirements.txt."
        ) from exc

    if not path.exists():
        raise PDFReadError(f"PDF file not found: {path}")

    logger.debug("Extracting text from PDF: %s", path)

    try:
        with pdfplumber.open(path) as pdf:
            pages_text: list[str] = []
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_text.append(text)
                else:
                    logger.debug("Page %d yielded no text (image-only?)", i + 1)
    except Exception as exc:
        raise PDFReadError(f"Failed to open or read PDF '{path}': {exc}") from exc

    raw = "\n".join(pages_text).strip()
    if not raw:
        raise PDFReadError(
            f"PDF '{path}' yielded no extractable text. "
            "It may be image-based or password-protected."
        )

    logger.debug("Extracted %d characters from %d pages", len(raw), len(pages_text))
    return raw


def extract_text_from_bytes(data: bytes, filename: str = "uploaded.pdf") -> str:
    """Extract raw text from PDF bytes (e.g. from a Streamlit file uploader).

    Args:
        data: Raw PDF bytes.
        filename: Used only in error messages for clarity.

    Returns:
        Raw text content as a single string.

    Raises:
        PDFReadError: if the bytes cannot be parsed or yield no text.
    """
    try:
        import io

        import pdfplumber
    except ImportError as exc:
        raise PDFReadError(
            "pdfplumber is not installed. Add it to requirements.txt."
        ) from exc

    logger.debug("Extracting text from PDF bytes (%d bytes) [%s]", len(data), filename)

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages_text: list[str] = []
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_text.append(text)
                else:
                    logger.debug("Page %d yielded no text", i + 1)
    except Exception as exc:
        raise PDFReadError(
            f"Failed to parse PDF bytes from '{filename}': {exc}"
        ) from exc

    raw = "\n".join(pages_text).strip()
    if not raw:
        raise PDFReadError(
            f"PDF '{filename}' yielded no extractable text. "
            "It may be image-based or password-protected."
        )

    logger.debug("Extracted %d characters from %d pages", len(raw), len(pages_text))
    return raw

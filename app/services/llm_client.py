"""
LLM client — thin wrapper around the Anthropic API.

All LLM calls in NextMatch route through this module.

Design:
  - All LLM output is treated as untrusted until validated by Pydantic.
  - API errors are logged before being re-raised.
  - Truncated responses (stop_reason != "end_turn") are logged as warnings.
  - Text is collected safely from all returned text blocks.
  - JSON extraction: fenced blocks and embedded spans are validated with
    json.loads before being accepted — no unverified candidates returned.
  - On any parse failure, LLMParseError is raised with the raw response.
  - Token usage is logged at DEBUG level for every call.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.services.config import get_config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_TOKENS = 4096


class LLMParseError(Exception):
    """Raised when the LLM response cannot be parsed into the expected schema."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


def _get_client() -> anthropic.Anthropic:
    cfg = get_config()
    if cfg.anthropic_api_key is None:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file before making LLM calls."
        )
    return anthropic.Anthropic(api_key=cfg.anthropic_api_key.get_secret_value())


def _collect_text(response: anthropic.types.Message) -> str:
    """Safely collect text from all text blocks in the API response.

    Warns if the response was truncated (stop_reason != 'end_turn').
    """
    if getattr(response, "stop_reason", None) not in ("end_turn", None):
        logger.warning(
            "LLM response may be incomplete | stop_reason=%s", response.stop_reason
        )

    parts: list[str] = [
        block.text
        for block in response.content
        if hasattr(block, "text") and isinstance(block.text, str)
    ]
    if not parts:
        raise LLMParseError(
            "LLM response contained no usable text content.",
            raw_response=str(response.content),
        )
    return "\n".join(parts).strip()


def call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = _MAX_TOKENS,
) -> str:
    """Make a raw LLM call and return the text response.

    Prefer call_llm_structured when a Pydantic model is expected.

    Raises:
        ValueError: if ANTHROPIC_API_KEY is not configured.
        LLMParseError: if the response contains no usable text.
        anthropic.APIError: on API-level errors (logged before re-raising).
    """
    cfg = get_config()
    client = _get_client()

    logger.debug(
        "LLM call | model=%s | system_len=%d | user_len=%d",
        cfg.model, len(system_prompt), len(user_prompt),
    )

    try:
        response = client.messages.create(
            model=cfg.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as exc:
        logger.error("Anthropic API error: %s", exc)
        raise

    logger.debug(
        "LLM response | input_tokens=%d | output_tokens=%d | stop_reason=%s",
        response.usage.input_tokens,
        response.usage.output_tokens,
        response.stop_reason,
    )

    return _collect_text(response)


def call_llm_structured(
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    *,
    max_tokens: int = _MAX_TOKENS,
) -> T:
    """Make an LLM call and parse the response into a Pydantic model.

    The system prompt should instruct the model to respond with valid JSON.

    Raises:
        LLMParseError: if no valid JSON is found or schema validation fails.
        ValueError: if ANTHROPIC_API_KEY is not configured.
        anthropic.APIError: on API-level errors.
    """
    raw = call_llm(system_prompt, user_prompt, max_tokens=max_tokens)
    data = _extract_and_parse_json(raw)

    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        logger.error(
            "LLM response failed schema validation (%s): %s",
            response_model.__name__, exc,
        )
        raise LLMParseError(
            f"LLM response failed validation for {response_model.__name__}: {exc}",
            raw_response=raw,
        ) from exc


def _extract_and_parse_json(text: str) -> Any:
    """Extract and parse the first valid JSON object or array from text.

    Candidates are tested with json.loads before being accepted.

    Extraction order:
      1. Content inside fenced blocks (```json ... ``` or ``` ... ```).
      2. Balanced-brace / balanced-bracket spans found by character scan,
         starting from the first { or [ in the text.

    Raises:
        LLMParseError: if no candidate successfully parses as JSON.
    """
    text = text.strip()

    # 1. Fenced block — validated with json.loads before accepting.
    for fenced_match in re.finditer(r"```(?:json)?\s*\n?([\s\S]*?)```", text):
        candidate = fenced_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue  # fenced block was not valid JSON; keep scanning

    # 2. Balanced-brace / bracket scanner — returns first span that parses.
    for start_char, end_char in (("{", "}"), ("[", "]")):
        pos = 0
        while True:
            start = text.find(start_char, pos)
            if start == -1:
                break
            end = _find_matching_close(text, start, start_char, end_char)
            if end == -1:
                break  # no closing bracket found; stop scanning this type
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pos = start + 1  # advance past this start position and retry

    logger.error(
        "No valid JSON found in LLM response | raw[:500]=%s", text[:500]
    )
    raise LLMParseError(
        "No valid JSON object or array found in LLM response.",
        raw_response=text,
    )


def _find_matching_close(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Return the index of the closing character matching text[start].

    Respects string literals and escape sequences.
    Returns -1 if no match is found.
    """
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1

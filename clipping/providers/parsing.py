"""Strict local-output parsing for the vLLM provider."""

import json
import re

from .base import InvalidOutputError


def clean_text(content):
    if not isinstance(content, str) or not content.strip():
        raise InvalidOutputError("vLLM returned empty content.")
    text = content.strip()
    if text.startswith(" thinking"):
        match = re.match(r"^ thinking.*?</think>\s*", text, re.DOTALL)
        if not match:
            raise InvalidOutputError("vLLM thinking output was truncated.")
        text = text[match.end():].strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if not match:
            raise InvalidOutputError("vLLM JSON fence is incomplete.")
        text = match.group(1).strip()
    if not text:
        raise InvalidOutputError("vLLM produced no final answer.")
    return text


def parse_clips(content, schema):
    from jsonschema import Draft202012Validator

    def invalid_constant(_):
        raise ValueError

    try:
        value = json.loads(clean_text(content), parse_constant=invalid_constant)
    except (ValueError, TypeError):
        raise InvalidOutputError("vLLM must produce one complete JSON object with a clips field.") from None

    error = next(Draft202012Validator(schema).iter_errors(value), None)
    if error is not None:
        raise InvalidOutputError("vLLM output does not satisfy the requested clip schema.")
    return value["clips"]

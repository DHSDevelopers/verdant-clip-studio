"""Shared execution-path preflight and local-only temporal validation."""

import math
import re
from pathlib import Path

from .base import InvalidOutputError, ProviderConfigError


def validate_analysis_config(cfg, *, probe=False, check_cache=True):
    cached = getattr(cfg, "load_gemini_json", False)
    voiceover = getattr(cfg, "voiceover", False)
    provider = getattr(cfg, "ai_provider", "gemini")
    if cached and check_cache and not (Path(cfg.outputs_dir) / "gemini_response.json").is_file():
        raise ProviderConfigError(
            "Cached AI JSON not found. Disable Bypass AI to run a fresh analysis."
        )
    if cached and not voiceover:
        return
    if provider == "vllm":
        from .config import vllm_config_values

        vllm_config_values(vars(cfg))
        if probe:
            from .vllm import VllmProvider

            with VllmProvider.from_cfg(cfg) as local:
                local.validate()
        return
    if provider not in {"gemini", "nvidia"}:
        raise ProviderConfigError("Unknown AI provider.")
    if voiceover and not getattr(cfg, "api_key_gemini", ""):
        raise ProviderConfigError("GOOGLE_API_KEY is required for cloud voiceover.")
    if cached:
        return
    if provider == "nvidia" and getattr(cfg, "api_key_nvidia", ""):
        return
    if not getattr(cfg, "api_key_gemini", ""):
        key = "NVIDIA_API_KEY or GOOGLE_API_KEY" if provider == "nvidia" else "GOOGLE_API_KEY"
        raise ProviderConfigError(f"{key} not found. Set it in .env or in Studio Settings.")


_STAMP = re.compile(r"^\[(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\]\s*", re.MULTILINE)


def transcript_end(transcript):
    for line in transcript.splitlines():
        if line.lstrip().startswith("[") and _STAMP.match(line) is None:
            raise ProviderConfigError("Transcript contains an invalid timestamp line.")
    pairs = [(float(m[1]), float(m[2])) for m in _STAMP.finditer(transcript)]
    if not pairs or any(not math.isfinite(s + e) or s < 0 or e < s for s, e in pairs):
        raise ProviderConfigError("Transcript must contain valid [start - end] timestamps.")
    end = max(e for _, e in pairs)
    if end <= 0:
        raise ProviderConfigError("Transcript duration must be greater than zero.")
    return end


def _number(value):
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        )
    except OverflowError:
        valid = False
    if not valid:
        raise InvalidOutputError("Timestamps and viral scores must be finite numbers.")
    return value


def _interval(item, low, high, *, start="start_time", end="end_time"):
    try:
        a, b = _number(item[start]), _number(item[end])
    except (KeyError, TypeError):
        raise InvalidOutputError("A clip/segment timestamp field is missing.") from None
    if not low <= a < b <= high:
        raise InvalidOutputError("A timestamp is outside the source range or reversed.")
    return a, b


def _ordered_intervals(items, low, high):
    last = low
    for item in items:
        start, end = _interval(item, low, high)
        if start < last:
            raise InvalidOutputError("Segments must be ordered and non-overlapping.")
        last = end


def validate_clips(clips, *, source_end, requested_clips, min_duration=20, max_duration=179):
    if not clips or len(clips) > requested_clips:
        raise InvalidOutputError("Clip count is empty or exceeds the requested amount.")
    intervals = []
    for item in clips:
        a, b = _interval(item, 0, source_end)
        if not min_duration <= b - a <= max_duration:
            raise InvalidOutputError(
                f"Clip duration must be between {min_duration}-{max_duration} seconds."
            )
        if not 1 <= _number(item["viral_score"]) <= 100:
            raise InvalidOutputError("Viral score must be 1-100.")
        _interval(item, a, b, start="hook_start_time", end="hook_end_time")
        _ordered_intervals(item.get("keep_segments", []), a, b)
        _ordered_intervals(item.get("broll_list", []), a, b)
        for hook in (item.get("hook_v2") or {}).get("items", []):
            _interval(hook, a, b)
        if (item.get("hook_v2") or {}).get("enabled") and not (item.get("hook_v2") or {}).get("items"):
            raise InvalidOutputError("Hook V2 is enabled but has no segments.")
        intervals.append((a, b))
    ordered = sorted(intervals)
    if any(right[0] < left[1] for left, right in zip(ordered, ordered[1:])):
        raise InvalidOutputError("Clips overlap; choose distinct moments.")
    return clips

"""Renderer readiness probe, used before any paid AI work starts."""

from __future__ import annotations

import importlib.util
import shutil


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def get_readiness() -> dict:
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "opencv": _has_module("cv2"),
        "numpy": _has_module("numpy"),
        "pillow": _has_module("PIL"),
        "yt_dlp": _has_module("yt_dlp"),
        "faster_whisper": _has_module("faster_whisper"),
    }
    # Rendering can run with yt-dlp subtitles or an upload; Whisper is only
    # required when the source has no usable subtitles.
    required = ["ffmpeg", "ffprobe", "opencv", "numpy", "pillow"]
    missing = [name for name in required if not checks[name]]
    return {
        "ready": not missing,
        "checks": checks,
        "missing": missing,
        "whisper_available": checks["faster_whisper"],
    }

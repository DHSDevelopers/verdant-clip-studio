"""Small shared helpers."""

import os


def format_seconds(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def escape_ffmpeg_filter_value(value: str) -> str:
    """Escape a path for use inside an FFmpeg filtergraph argument."""
    text = os.path.abspath(str(value))
    text = text.replace("\\", "/")
    for old, new in ((":", "\\:"), ("'", "\\'"), ("[", "\\["), ("]", "\\]")):
        text = text.replace(old, new)
    return text

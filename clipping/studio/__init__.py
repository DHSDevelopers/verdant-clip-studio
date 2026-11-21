"""Renderer facade: public entry points for the clipping pipeline."""

from .audio_bgm import build_bgm_filter, get_local_bgm_file
from .broll import crop_center_broll, download_pexels_broll
from .core import (
    download_google_font,
    estimate_speaker_count_from_video,
    proses_klip,
    register_fonts_for_libass,
    siapkan_font_tipografi,
)
from .effects import siapkan_glitch_video
from .ffmpeg_utils import (
    build_ffmpeg_progress_cmd,
    detect_video_encoder,
    get_mp4_encode_args,
    get_ts_encode_args,
    open_ffmpeg_video_writer,
    probe_duration,
    run_ffmpeg_with_progress,
)
from .helpers import escape_ffmpeg_filter_value, format_seconds
from .render_hybrid import buat_video_hybrid
from .subtitles import buat_file_ass
from .thumbnail import buat_thumbnail
from .utils import _get_render_dims, _is_vertical_ratio

__all__ = [
    "proses_klip",
    "buat_video_hybrid",
    "buat_file_ass",
    "siapkan_glitch_video",
    "detect_video_encoder",
    "get_ts_encode_args",
    "get_mp4_encode_args",
    "_get_render_dims",
    "_is_vertical_ratio",
    "estimate_speaker_count_from_video",
    "download_pexels_broll",
    "get_local_bgm_file",
    "build_bgm_filter",
    "buat_thumbnail",
    "siapkan_font_tipografi",
    "probe_duration",
]

"""
clipping.config — master configuration.

Holds every default used by the pipeline and builds the runtime config
namespace from CLI flags (or, in Studio, from the API payload adapter).
"""

import argparse
import hashlib
import os
import re
from types import SimpleNamespace

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional for the renderer-only path
    pass

BASE_DIR = os.getcwd()
FONT_DIR = os.path.abspath(os.path.join(BASE_DIR, "custom_fonts"))

# ---------------------------------------------------------------- main settings
JUMLAH_CLIP = 7
PILIHAN_RASIO = "9:16"

# ------------------------------------------------------------ content & hooks
MAX_KATA_PER_SUBTITLE = 5
DURASI_HOOK = 3
USE_BROLL = True
USE_HOOK_GLITCH = True
USE_SPLIT_SCREEN = False
USE_CAMERA_SWITCH = False
DIARIZATION_NUM_SPEAKERS = "auto"
SWITCH_HOLD_DURATION = 2.0
SWITCH_BLEND_DURATION = 0.0
SOURCE_PLATFORM = "youtube"

# -------------------------------------------------- subtitle & typography (ASS)
USE_ADVANCED_TEXT = False
USE_ADVANCED_TEXT_ON_HOOK = False
USE_KARAOKE_EFFECT = True
GAYA_FONT_AKTIF = "HORMOZI"

DAFTAR_FONT = {
    "DEFAULT": {
        "utama": {
            "nama": "Montserrat Black",
            "file": "Montserrat-Black.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf",
            "bold": 1,
        },
        "khusus": {
            "nama": "Montserrat Medium",
            "file": "Montserrat-Medium.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Medium.ttf",
            "bold": 0,
        },
    },
    "STORYTELLER": {
        "utama": {
            "nama": "Inter",
            "file": "Inter-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "khusus": {
            "nama": "Lora",
            "file": "Lora-Bold.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/lora@latest/latin-700-normal.ttf",
            "bold": 1,
        },
    },
    "HORMOZI": {
        "utama": {
            "nama": "Montserrat",
            "file": "Montserrat-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "khusus": {
            "nama": "Anton",
            "file": "Anton-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/anton@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
    "CINEMATIC": {
        "utama": {
            "nama": "Roboto",
            "file": "Roboto-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/roboto@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "khusus": {
            "nama": "Bebas Neue",
            "file": "BebasNeue-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
}

ASS_ALIGN_916 = 2
ASS_MARGIN_916 = 450
ASS_FONT_916 = 90
SCALE_KATA_KHUSUS_916 = ASS_FONT_916 + 120

ASS_ALIGN_169 = 2
ASS_MARGIN_169 = 70
ASS_FONT_169 = 80
SCALE_KATA_KHUSUS_169 = ASS_FONT_169 + 120

# ASS colours are BGR: &H[BB][GG][RR]&
WARNA_KATA_KHUSUS = "&HFFFFFF&"

# ------------------------------------------------------------ external assets
NAMA_FONT_THUMBNAIL = "Montserrat-Black.ttf"
URL_FONT_THUMBNAIL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf"
)
URL_GLITCH_VIDEO = "https://www.youtube.com/watch?v=5nBcNRYmjs0"
MEDIAPIPE_MODEL_FILENAME = "blaze_face_short_range_v1.tflite"
URL_MEDIAPIPE_MODEL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)

# ------------------------------------------------------------- BGM & ducking
USE_AUTO_BGM = True
BGM_BASE_VOLUME = 0.25
BGM_MODE = "ducking"
BGM_MOODS = ["chill", "epic", "sad", "upbeat", "suspense"]
BGM_DIR = os.path.abspath(os.path.join(BASE_DIR, "assets", "bgm"))

# --------------------------------------------------------------------- encode
WHISPER_MODEL = "large-v3"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"
DOWNLOAD_SOURCE_HEIGHT = "max"
VIDEO_QUALITY_CQ = 23
VIDEO_QUALITY_CRF = 20
VIDEO_PRESET = "auto"
VIDEO_SCALE_ALGO = "lanczos"
RENDER_OUTPUT_HEIGHT = 1080

# ------------------------------------------------------------------ AI models
AI_PROVIDER = "gemini"
NVIDIA_MODEL = "deepseek-ai/deepseek-v4-pro"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"

# --------------------------------------------------------------------- helpers


def _make_url_slug(url: str, index: int) -> str:
    """Generate a short, filesystem-safe slug from a URL for output isolation."""
    video_id = ""
    if "youtube.com" in url or "youtu.be" in url:
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        if match:
            video_id = match.group(1)
    elif "tiktok.com" in url:
        match = re.search(r"/video/(\d+)", url)
        if match:
            video_id = match.group(1)[:12]
    elif "instagram.com" in url:
        match = re.search(r"/(?:reel|p)/([a-zA-Z0-9_-]+)", url)
        if match:
            video_id = match.group(1)[:12]

    if video_id:
        return f"video_{index + 1}_{video_id}"
    short_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"video_{index + 1}_{short_hash}"


def _parse_speakers(val: str):
    if val.lower() == "auto":
        return "auto"
    try:
        return int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{val}' is not a valid integer or 'auto'")


def _parse_download_height(val: str):
    if val.lower() == "max":
        return "max"
    try:
        parsed = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{val}' is not valid. Use 'max' or an integer height (e.g. 1080, 1440, 2160)."
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Download source height must be a positive integer.")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verdant Clip — AI Auto-Clipper & Teaser Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument("--url", "-u", required=False, default=None, nargs="+",
                   help="One or more video URLs to process (space-separated).")
    p.add_argument("--yt-cookies", type=str, default=None,
                   help="Browser name (e.g. 'chrome') or path to cookies.txt for yt-dlp")
    p.add_argument("--source", choices=["youtube", "tiktok", "instagram", "gdrive"],
                   default=SOURCE_PLATFORM, help="Video source platform.")
    p.add_argument("--tiktok", action="store_true", default=False,
                   help="[DEPRECATED] Use --source tiktok instead.")
    p.add_argument("--clips", "-n", type=int, default=JUMLAH_CLIP,
                   help="Number of highlight clips to generate")
    p.add_argument("--ratio", "-r", default=PILIHAN_RASIO,
                   choices=["9:16", "16:9", "1:1", "3:4", "4:5"],
                   help="Output aspect ratio")
    p.add_argument("--source-height", type=_parse_download_height,
                   default=DOWNLOAD_SOURCE_HEIGHT,
                   help="Preferred source download max height ('max' or an integer).")
    p.add_argument("--render-height", default=str(RENDER_OUTPUT_HEIGHT),
                   help="Target output height, or 'source'.")

    p.add_argument("--words-per-sub", type=int, default=MAX_KATA_PER_SUBTITLE,
                   help="Max words per karaoke subtitle group")
    p.add_argument("--hook-duration", type=int, default=DURASI_HOOK,
                   help="Hook teaser duration in seconds")
    p.add_argument("--hook-source", default=None,
                   help="Google Drive URL or local path for a custom hook video (.mp4)")
    p.add_argument("--hook-source-start", type=float, default=0.0,
                   help="Start time in seconds for the custom hook video")
    p.add_argument("--no-broll", action="store_true", help="Disable B-roll footage")
    p.add_argument("--no-hook", action="store_true", help="Disable hook glitch teaser")
    p.add_argument("--cleanup-source", action="store_true", default=False,
                   help="Auto-delete the downloaded source video after rendering.")
    p.add_argument("--no-bgm", action="store_true", help="Disable background music")
    p.add_argument("--bgm-mode", choices=["ducking", "background"], default=BGM_MODE,
                   help="BGM mixing mode.")
    p.add_argument("--no-karaoke", action="store_true",
                   help="Disable karaoke highlight effect")
    p.add_argument("--split-screen", action="store_true", default=USE_SPLIT_SCREEN,
                   help="Enable split-screen for podcasts (9:16, requires HF_TOKEN).")
    p.add_argument("--diarization-speakers", type=_parse_speakers,
                   default=DIARIZATION_NUM_SPEAKERS,
                   help="Number of speakers for diarization, or 'auto'.")
    p.add_argument("--camera-switch", action="store_true", default=USE_CAMERA_SWITCH,
                   help="Enable camera-switch mode for podcasts (9:16, requires HF_TOKEN).")
    p.add_argument("--switch-hold-duration", type=float, default=SWITCH_HOLD_DURATION,
                   help="Minimum seconds to hold a speaker before switching.")
    p.add_argument("--switch-blend-duration", type=float, default=SWITCH_BLEND_DURATION,
                   help="Blend duration on speaker switch (0 = instant).")
    p.add_argument("--no-subs", action="store_true", help="Disable all subtitle rendering")
    p.add_argument("--dynamic-split", action="store_true",
                   help="Switch between full-screen and split-screen automatically.")
    p.add_argument("--split-trigger", choices=["diarization", "face"], default="diarization",
                   help="Trigger used to decide when to split the screen.")
    p.add_argument("--split-zoom", type=float, default=1.0,
                   help="Zoom factor for split-screen panels.")
    p.add_argument("--split-v-align", type=float, default=0.5,
                   help="Vertical alignment for split-screen panels.")
    p.add_argument("--split-auto-zoom", action="store_true",
                   help="Auto-zoom split panels until one person is visible.")
    p.add_argument("--split-max-zoom", type=float, default=2.5,
                   help="Maximum auto-zoom factor.")

    p.add_argument("--font-style", default=GAYA_FONT_AKTIF,
                   choices=list(DAFTAR_FONT), help="Font style preset")
    p.add_argument("--advanced-text", action="store_true", default=USE_ADVANCED_TEXT,
                   help="Enable advanced kinetic typography")
    p.add_argument("--advanced-text-hook", action="store_true",
                   default=USE_ADVANCED_TEXT_ON_HOOK,
                   help="Enable advanced typography on hook")

    p.add_argument("--use-dlp-subs", action="store_true",
                   help="Use yt-dlp subtitles and skip Whisper when available")
    p.add_argument("--whisper-model", default=WHISPER_MODEL, help="Faster-Whisper model size")
    p.add_argument("--whisper-device", default=WHISPER_DEVICE, choices=["cuda", "cpu", "auto"],
                   help="Device for Whisper inference")
    p.add_argument("--whisper-compute-type", default=WHISPER_COMPUTE_TYPE,
                   help="Compute type for Whisper (float16, int8, ...)")

    p.add_argument("--face-detector", choices=["mediapipe", "yolo"], default="mediapipe",
                   help="AI model for face tracking")
    p.add_argument("--yolo-size", choices=["8n", "8s", "8m", "8n_v2", "9c"], default="8m",
                   help="YOLO face model version/size")
    p.add_argument("--ai-provider", choices=["gemini", "nvidia", "vllm"], default=AI_PROVIDER,
                   help="AI provider for video analysis")
    p.add_argument("--nvidia-model", default=NVIDIA_MODEL, help="NVIDIA NIM model")
    p.add_argument("--gemini-model", default=GEMINI_MODEL, help="Gemini model name")
    p.add_argument("--vllm-model", default=None, help="vLLM served model/alias")
    p.add_argument("--local-base-url", dest="vllm_base_url", default=None,
                   help="vLLM service URL, with optional /v1")
    p.add_argument("--local-max-tokens", type=int, default=None,
                   help="vLLM output token budget")
    p.add_argument("--local-context-limit", dest="vllm_context_limit", type=int, default=None,
                   help="Optional vLLM client context ceiling")
    p.add_argument("--local-timeout", dest="vllm_timeout", type=float, default=None,
                   help="vLLM request/retry deadline in seconds")
    p.add_argument("--gemini-fallback-model", default=GEMINI_FALLBACK_MODEL,
                   help="Gemini fallback model if the main model fails")
    p.add_argument("--load-gemini-json", action="store_true",
                   help="Reuse outputs/<job>/gemini_response.json instead of calling AI")
    p.add_argument("--box-face-detection", action="store_true",
                   help="Draw a box around tracked faces (debug)")
    p.add_argument("--dev-mode", action="store_true", help="Developer tracking visualization")
    p.add_argument("--dev-mode-with-output", action="store_true",
                   help="Render both dev visualization and final output")
    p.add_argument("--dev-mode-with-output-merge", action="store_true",
                   help="Render a merged side-by-side dev/final video")
    p.add_argument("--track-lines", action="store_true", help="Draw crosshair tracking lines")
    p.add_argument("--static-crop", action="store_true",
                   help="Disable face tracking and use a static center crop")

    p.add_argument("--track-step", type=float, default=None,
                   help="Face detection frequency in seconds (default 0.25)")
    p.add_argument("--track-deadzone", type=float, default=None,
                   help="Camera deadzone ratio (default 0.15)")
    p.add_argument("--track-smooth", type=float, default=None,
                   help="Camera smoothing speed (default 0.30)")
    p.add_argument("--track-jitter", type=int, default=None,
                   help="Pixel jitter threshold (default 5)")
    p.add_argument("--track-snap", type=float, default=None,
                   help="Face jump snap threshold (default 0.25)")
    p.add_argument("--track-conf", type=float, default=0.55,
                   help="[Experimental] Face detection confidence threshold")
    p.add_argument("--track-smooth-window", type=int, default=12,
                   help="[Experimental] Majority-vote window for layout stability")
    p.add_argument("--scene-cut-threshold", type=int, default=18,
                   help="[Experimental] Camera-cut detection threshold")
    p.add_argument("--track-iou-threshold", type=float, default=0.2,
                   help="[Experimental] Box overlap merge threshold")
    p.add_argument("--video-bitrate", default="auto",
                   help="Target video bitrate (e.g. 8M, 12M, auto)")
    p.add_argument("--video-sharpen", action="store_true",
                   help="Apply a subtle sharpening filter")
    p.add_argument("--video-cq", type=int, default=VIDEO_QUALITY_CQ,
                   help="NVENC constant quality (lower is sharper)")
    p.add_argument("--video-crf", type=int, default=VIDEO_QUALITY_CRF,
                   help="libx264 CRF (lower is sharper)")
    p.add_argument("--video-preset", default=VIDEO_PRESET,
                   help="Encoder preset, or 'auto'")
    p.add_argument("--video-scale-algo", choices=["lanczos", "bicubic", "bilinear", "area"],
                   default=VIDEO_SCALE_ALGO, help="Resize algorithm for OpenCV scaling")

    hook_v2 = p.add_argument_group("Hook V2 & Segment Trimming")
    hook_v2.add_argument("--hook-v2", action="store_true", default=False,
                         help="Enable Multi-Hook Intro V2 (micro-hooks with flash transitions).")
    hook_v2.add_argument("--hook-v2-items", type=int, default=3,
                         help="Number of micro-hooks to generate in V2 mode.")
    hook_v2.add_argument("--hook-v2-style", default="controversial_fast_glitch",
                         help="Style prompt hint for the AI hook selection.")
    hook_v2.add_argument("--white-flash-duration", type=float, default=0.12,
                         help="Duration of the flash transition between hooks.")
    hook_v2.add_argument("--no-segment-trim", action="store_true", default=False,
                         help="Disable AI segment trimming.")
    hook_v2.add_argument("--silence-trim", action="store_true", default=False,
                         help="Instruct the AI to aggressively trim silence.")

    vo = p.add_argument_group("Voice-Over Commentary (TTS)")
    vo.add_argument("--voiceover", action="store_true", default=False,
                    help="Enable AI voice-over commentary using Gemini + edge-tts.")
    vo.add_argument("--voiceover-voice", default="en-GB-MaisieNeural",
                    help="TTS voice for edge-tts.")
    vo.add_argument("--voiceover-lang", choices=["id", "en"], default="en",
                    help="Language for the commentary script.")
    vo.add_argument("--voiceover-style", choices=["analysis", "reaction", "lesson", "summary"],
                    default="analysis", help="Style of the generated commentary.")
    vo.add_argument("--voiceover-length", choices=["short", "normal", "long"], default="short",
                    help="Length of the generated commentary.")
    vo.add_argument("--voiceover-volume", type=float, default=1.0,
                    help="Volume of the voice-over audio.")
    vo.add_argument("--original-volume", type=float, default=0.15,
                    help="Original audio volume while voice-over is active.")
    vo.add_argument("--edge-glow", action="store_true", default=False,
                    help="Apply ambient edge glow to the entire output.")
    vo.add_argument("--edge-glow-mode", choices=["default", "smooth", "full"], default="smooth",
                    help="Edge glow rendering strategy.")

    wm = p.add_argument_group("Watermark")
    wm.add_argument("--watermark", action="store_true", default=False,
                    help="Enable watermark overlay on rendered clips.")
    wm.add_argument("--text", default=None, help="Watermark text to overlay.")
    wm.add_argument("--image", default=None, help="Path to a watermark image.")
    wm.add_argument("--opacity", type=int, default=70, help="Watermark opacity (1-100).")
    wm.add_argument("--position", default="center-right",
                    choices=["top-left", "top-center", "top-right", "center-left",
                             "center", "center-right", "bottom-left", "bottom-center",
                             "bottom-right"],
                    help="Watermark position on the video frame.")
    wm.add_argument("--padding", type=int, default=0,
                    help="Watermark padding from the nearest edge in pixels.")
    wm.add_argument("--watermark-font-size", type=int, default=0,
                    help="Watermark font size in pixels (0 = auto).")
    wm.add_argument("--watermark-scale", type=int, default=15,
                    help="Watermark image height as %% of frame height.")
    return p


def build_config(argv: list[str] | None = None) -> SimpleNamespace:
    """Parse CLI args and merge with defaults into a config namespace."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.url:
        parser.error("--url is required.")

    url_list = args.url if isinstance(args.url, list) else ([args.url] if args.url else [])

    if args.watermark:
        if not args.text and not args.image:
            parser.error("--watermark requires --text or --image.")
        if not (1 <= args.opacity <= 100):
            parser.error(f"--opacity must be between 1-100, got: {args.opacity}")
        if args.padding < 0:
            parser.error(f"--padding must not be negative, got: {args.padding}")
        if args.watermark_font_size < 0:
            parser.error("--watermark-font-size must not be negative")
        if not (1 <= args.watermark_scale <= 100):
            parser.error("--watermark-scale must be between 1-100")
        if args.image:
            if not os.path.exists(args.image):
                parser.error(f"Watermark image not found: {args.image}")
            valid_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
            if not args.image.lower().endswith(valid_exts):
                parser.error(
                    f"Unsupported watermark image format: {args.image}. "
                    f"Supported: {', '.join(valid_exts)}"
                )

    base_dir = os.getcwd()
    outputs_dir = os.path.abspath(os.path.join(base_dir, "outputs"))
    os.makedirs(outputs_dir, exist_ok=True)
    font_dir = os.path.abspath(os.path.join(base_dir, "custom_fonts"))
    os.makedirs(font_dir, exist_ok=True)

    cfg = SimpleNamespace(
        base_dir=base_dir,
        outputs_dir=outputs_dir,
        font_dir=font_dir,
        file_video_asli=os.path.abspath(os.path.join(base_dir, "video_asli.mp4")),
        file_font_thumbnail=os.path.abspath(os.path.join(base_dir, NAMA_FONT_THUMBNAIL)),
        file_mediapipe_model=os.path.abspath(os.path.join(base_dir, MEDIAPIPE_MODEL_FILENAME)),
        face_detector=args.face_detector,
        yolo_size=args.yolo_size,
        url_yolo_model=f"https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov{args.yolo_size}.pt",
        file_yolo_model=os.path.abspath(os.path.join(base_dir, f"face_yolov{args.yolo_size}.pt")),
        api_key_gemini=os.environ.get("GOOGLE_API_KEY", ""),
        hf_token=os.environ.get("HF_TOKEN", ""),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        source_platform="tiktok" if args.tiktok else args.source,
        url_youtube=url_list[0] if len(url_list) == 1 else url_list,
        url_list=url_list,
        yt_cookies=args.yt_cookies,
        cleanup_source=args.cleanup_source,
        jumlah_clip=args.clips,
        pilihan_rasio=args.ratio,
        download_source_height=args.source_height,
        render_output_height=args.render_height,
        max_kata_per_subtitle=args.words_per_sub,
        durasi_hook=args.hook_duration,
        hook_source=args.hook_source,
        hook_source_start=args.hook_source_start,
        hook_v2=args.hook_v2,
        hook_v2_items=args.hook_v2_items,
        hook_v2_style=args.hook_v2_style,
        white_flash_duration=args.white_flash_duration,
        no_segment_trim=args.no_segment_trim,
        silence_trim=args.silence_trim,
        use_broll=not args.no_broll,
        use_hook_glitch=not args.no_hook,
        use_auto_bgm=not args.no_bgm,
        use_karaoke_effect=not args.no_karaoke,
        use_split_screen=args.split_screen,
        use_dynamic_split=args.dynamic_split,
        split_trigger=args.split_trigger,
        use_camera_switch=args.camera_switch,
        diarization_num_speakers=args.diarization_speakers,
        switch_hold_duration=args.switch_hold_duration,
        switch_blend_duration=args.switch_blend_duration,
        split_zoom=args.split_zoom,
        split_v_align=args.split_v_align,
        split_auto_zoom=args.split_auto_zoom,
        split_max_zoom=args.split_max_zoom,
        no_subs=args.no_subs,
        gaya_font_aktif=args.font_style,
        daftar_font=DAFTAR_FONT,
        use_advanced_text=args.advanced_text,
        use_advanced_text_on_hook=args.advanced_text_hook,
        ass_align_916=ASS_ALIGN_916,
        ass_margin_916=ASS_MARGIN_916,
        ass_font_916=ASS_FONT_916,
        scale_kata_khusus_916=SCALE_KATA_KHUSUS_916,
        ass_align_169=ASS_ALIGN_169,
        ass_margin_169=ASS_MARGIN_169,
        ass_font_169=ASS_FONT_169,
        scale_kata_khusus_169=SCALE_KATA_KHUSUS_169,
        warna_kata_khusus=WARNA_KATA_KHUSUS,
        url_font_thumbnail=URL_FONT_THUMBNAIL,
        url_glitch_video=URL_GLITCH_VIDEO,
        url_mediapipe_model=URL_MEDIAPIPE_MODEL,
        bgm_base_volume=BGM_BASE_VOLUME,
        bgm_mode=args.bgm_mode,
        bgm_moods=BGM_MOODS,
        bgm_dir=BGM_DIR,
        use_dlp_subs=args.use_dlp_subs,
        whisper_model=args.whisper_model,
        whisper_device=args.whisper_device,
        whisper_compute_type=args.whisper_compute_type,
        ai_provider=args.ai_provider,
        api_key_nvidia=os.environ.get("NVIDIA_API_KEY", ""),
        nvidia_model=args.nvidia_model,
        gemini_model=args.gemini_model,
        gemini_fallback_model=args.gemini_fallback_model,
        load_gemini_json=args.load_gemini_json,
        track_step=args.track_step,
        track_deadzone=args.track_deadzone,
        track_smooth=args.track_smooth,
        track_jitter=args.track_jitter,
        track_snap=args.track_snap,
        track_conf=args.track_conf,
        track_smooth_window=args.track_smooth_window,
        scene_cut_threshold=args.scene_cut_threshold,
        track_iou_threshold=args.track_iou_threshold,
        video_quality_cq=args.video_cq,
        video_quality_crf=args.video_crf,
        video_bitrate=args.video_bitrate,
        video_sharpen=args.video_sharpen,
        video_preset=args.video_preset,
        video_scale_algo=args.video_scale_algo,
        box_face_detection=args.box_face_detection,
        dev_mode=args.dev_mode,
        dev_mode_with_output=args.dev_mode_with_output,
        dev_mode_with_output_merge=args.dev_mode_with_output_merge,
        track_lines=args.track_lines,
        static_crop=args.static_crop,
        voiceover=args.voiceover,
        voiceover_voice=args.voiceover_voice,
        voiceover_lang=args.voiceover_lang,
        voiceover_style=args.voiceover_style,
        voiceover_length=args.voiceover_length,
        voiceover_volume=args.voiceover_volume,
        original_volume=args.original_volume,
        edge_glow=args.edge_glow,
        edge_glow_mode=args.edge_glow_mode,
        watermark_enabled=args.watermark,
        watermark_text=args.text,
        watermark_image=args.image,
        watermark_opacity=args.opacity,
        watermark_position=args.position,
        watermark_padding=args.padding,
        watermark_font_size=args.watermark_font_size,
        watermark_scale=args.watermark_scale,
        output_naming=None,
        watermark=True if args.watermark else False,
    )

    # Cache-only reruns need neither a live endpoint nor its former settings.
    if cfg.ai_provider == "vllm" and (not cfg.load_gemini_json or cfg.voiceover):
        from clipping.providers.config import vllm_config_values

        vars(cfg).update(vllm_config_values(vars(args)))
    return cfg

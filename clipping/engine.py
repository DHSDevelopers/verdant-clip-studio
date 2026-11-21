"""clipping.engine — acquisition, transcription and AI curation.

Stage 1  download (yt-dlp / gdown)
Stage 2  word-level transcript (Faster-Whisper, or yt-dlp JSON3 subtitles)
Stage 3  AI highlight + metadata analysis (Gemini / NVIDIA NIM / vLLM)
"""

import glob
import io
import json
import os
import re
import time

from .prompt import (
    MAX_CLIP_DURATION,
    MIN_CLIP_DURATION,
    TARGET_ACCOUNTS,
    get_analysis_prompt,
)

_PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "gdrive": "Google Drive",
}


# =============================================================================
# STAGE 1 — DOWNLOAD
# =============================================================================

def _build_ydl_format_selector(download_source_height) -> str:
    """Build the yt-dlp format selector; AV1 is excluded (no HW decode on most hosts)."""
    codec_filter = "[vcodec!*=av01]"
    if download_source_height == "max":
        return f"bestvideo{codec_filter}+bestaudio/best{codec_filter}"

    try:
        h_val = int(download_source_height)
    except (ValueError, TypeError):
        h_val = 0

    if 0 < h_val <= 1080:
        return (
            f"bestvideo[height<=?{h_val}][ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
            f"bestvideo[height<=?{h_val}]{codec_filter}+bestaudio/"
            f"best[height<=?{h_val}][ext=mp4]{codec_filter}/"
            f"best[height<=?{h_val}]{codec_filter}"
        )
    return (
        f"bestvideo[height<=?{download_source_height}]{codec_filter}+bestaudio/"
        f"best[height<=?{download_source_height}]{codec_filter}"
    )


def _extract_gdrive_file_id(url: str):
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def _download_gdrive(url: str, output_path: str) -> None:
    import gdown

    file_id = _extract_gdrive_file_id(url)
    if not file_id:
        raise RuntimeError(
            f"Could not extract a Google Drive file ID from: {url}\n"
            "      Supported: https://drive.google.com/file/d/FILE_ID/view "
            "or https://drive.google.com/open?id=FILE_ID"
        )
    print(f"      File ID: {file_id}")
    gdown.download(f"https://drive.google.com/uc?id={file_id}", output_path, quiet=False)


def _ydl_progress_hook(d: dict) -> None:
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        speed = d.get("speed")
        eta = d.get("eta")
        spd = f"{speed / 1024 / 1024:4.1f}MB/s" if speed else "  --MB/s"
        eta_s = f"{eta:>3}s" if eta is not None else " --s"
        if total:
            pct = downloaded / total * 100
            filled = int(20 * downloaded / total)
            bar = "#" * filled + " " * (20 - filled)
            print(
                f"\r      Download: {pct:3.0f}%|{bar}| "
                f"{downloaded / 1048576:.0f}/{total / 1048576:.0f}MB {spd} ETA {eta_s}   ",
                end="",
                flush=True,
            )
        else:
            print(f"\r      Download: {downloaded / 1048576:.0f}MB {spd}   ", end="", flush=True)
    elif status == "finished":
        print(flush=True)


def _apply_cookies(opts: dict, cookies) -> None:
    if not cookies:
        return
    if isinstance(cookies, bytes):
        opts["cookiefile"] = io.StringIO(cookies.decode("utf-8"))
    elif cookies.endswith(".txt") or os.path.isfile(cookies):
        opts["cookiefile"] = cookies
    else:
        opts["cookiesfrombrowser"] = (cookies, None, None, None)


def download_video(
    url: str,
    output_path: str,
    use_dlp_subs: bool = False,
    download_source_height="max",
    source_platform: str = "youtube",
    yt_cookies=None,
) -> None:
    from yt_dlp import YoutubeDL

    print(f"[1/3] Downloading video from {_PLATFORM_LABELS.get(source_platform, source_platform)}...")
    print(
        "      Source quality: highest available"
        if download_source_height == "max"
        else f"      Source quality: up to {download_source_height}p",
        flush=True,
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if source_platform == "gdrive":
        _download_gdrive(url, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(f"Google Drive download failed — no file at {output_path}")
        return

    uses_youtube_format = source_platform == "youtube"
    if uses_youtube_format:
        ydl_opts = {
            "format": _build_ydl_format_selector(download_source_height),
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_ydl_progress_hook],
            "extractor_args": {"youtube": ["player_client=android,web"]},
        }
    else:
        # H.264 preferred: TikTok's bytevc1/H.265 breaks PyAV on many hosts.
        ydl_opts = {
            "format": "bestvideo[vcodec^=h264]+bestaudio/best[vcodec^=h264]/best",
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_ydl_progress_hook],
        }

    if use_dlp_subs and uses_youtube_format:
        print("      Looking for automatic subtitles (en / id)...")
        for lang in ["en", "id"]:
            sub_opts = ydl_opts.copy()
            _apply_cookies(sub_opts, yt_cookies)
            sub_opts.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [lang],
                    "subtitlesformat": "json3",
                    "skip_download": True,
                }
            )
            try:
                with YoutubeDL(sub_opts) as ydl:
                    ydl.download([url])
                if glob.glob(output_path.replace(".mp4", ".*.json3")):
                    print(f"      Subtitle '{lang}' found; Whisper can be skipped.")
                    break
            except Exception as exc:
                print(f"      Subtitle '{lang}' unavailable ({exc}). Trying next option...")
    elif use_dlp_subs:
        print("      This platform has no automatic subtitles; Whisper will be used.")

    _apply_cookies(ydl_opts, yt_cookies)
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            print(
                f"      Downloading: {info.get('height', 'unknown')}p "
                f"(codec: {info.get('vcodec', 'unknown')})",
                flush=True,
            )
        except Exception as exc:
            print(f"      Could not probe media info: {exc}", flush=True)
        ydl.download([url])

    if not os.path.exists(output_path):
        raise RuntimeError(
            f"Download from {_PLATFORM_LABELS.get(source_platform, source_platform)} failed — "
            f"no file at {output_path}. Check that the URL is public and valid."
        )


# =============================================================================
# STAGE 2 — TRANSCRIPT
# =============================================================================

def parse_youtube_json3_subs(json_path: str, max_words_per_subtitle: int = 5):
    """Parse downloaded YouTube JSON3 subtitles into a transcript + word segments."""
    print("[2/3] Parsing YouTube JSON3 subtitles...")
    transkrip_lengkap = ""
    data_segmen = []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            subs_data = json.load(f)

        flat_words = []
        for event in subs_data.get("events", []):
            t_start = event.get("tStartMs", 0) / 1000.0
            duration = event.get("dDurationMs", 0) / 1000.0
            event_end = t_start + duration
            segs = event.get("segs", [])
            for i, seg in enumerate(segs):
                text = seg.get("utf8", "")
                if not text.strip() or text == "\n":
                    continue
                seg_start = t_start + seg.get("tOffsetMs", 0) / 1000.0
                if i < len(segs) - 1:
                    seg_end = t_start + segs[i + 1].get("tOffsetMs", 0) / 1000.0
                else:
                    seg_end = event_end
                if seg_end <= seg_start:
                    seg_end = seg_start + 1.0

                clean = text.replace("\n", " ").replace("\u200b", "").strip()
                clean = re.sub(r"<[^>]+>", "", clean)
                clean = re.sub(r"\[[\w\s]+\]", "", clean)
                clean = re.sub(r">>\s*", "", clean)
                clean = re.sub(r"[♪♫♬♩]", "", clean)
                clean = re.sub(r"^\s*-\s+", "", clean)
                clean = re.sub(r"\s{2,}", " ", clean).strip()
                if not clean:
                    continue

                words_in_seg = clean.split()
                per_word = (seg_end - seg_start) / len(words_in_seg)
                for w_idx, w_text in enumerate(words_in_seg):
                    w_start = seg_start + (w_idx * per_word)
                    flat_words.append({"word": w_text, "start": w_start, "end": w_start + per_word})

        for i in range(len(flat_words) - 1):
            if flat_words[i]["end"] > flat_words[i + 1]["start"]:
                flat_words[i]["end"] = max(
                    flat_words[i]["start"] + 0.1, flat_words[i + 1]["start"]
                )

        chunk_words = []
        chunk_start = 0.0
        for i, w in enumerate(flat_words):
            if not chunk_words:
                chunk_start = w["start"]
            chunk_words.append(w)
            if len(chunk_words) == max_words_per_subtitle or i == len(flat_words) - 1:
                chunk_text = " ".join(cw["word"] for cw in chunk_words)
                transkrip_lengkap += f"[{chunk_start:.1f} - {w['end']:.1f}] {chunk_text}\n"
                data_segmen.append({"start": chunk_start, "end": w["end"], "words": chunk_words})
                chunk_words = []
        return transkrip_lengkap, data_segmen

    except Exception as exc:
        print(f"Could not parse JSON3: {exc}")
        return "", []


def transcribe_video(
    video_path: str,
    max_words_per_subtitle: int = 5,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    whisper_model_instance=None,
):
    """Transcribe with Faster-Whisper and group words for karaoke subtitles."""
    from faster_whisper import WhisperModel

    print("[2/3] Transcribing with Faster-Whisper (word level)...")

    if whisper_model_instance is not None:
        model = whisper_model_instance
        print("      Reusing the pre-loaded Whisper model (batch mode).", flush=True)
    else:
        print(
            f"      Loading Whisper '{model_size}' ({device}) — the first run may download weights...",
            flush=True,
        )
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as exc:
            if device == "cuda":
                print(f"      CUDA Whisper unavailable ({exc}); falling back to CPU int8.")
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
            else:
                raise

    print("      Decoding audio and extracting features...", flush=True)
    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    transkrip_lengkap = ""
    data_segmen: list[dict] = []
    for segment in segments:
        transkrip_lengkap += f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}\n"
        if not segment.words:
            continue
        chunk_words: list[dict] = []
        chunk_start = 0.0
        words = list(segment.words)
        for i, w in enumerate(words):
            if not chunk_words:
                chunk_start = w.start
            chunk_words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
            if len(chunk_words) == max_words_per_subtitle or i == len(words) - 1:
                data_segmen.append({"start": chunk_start, "end": w.end, "words": chunk_words})
                chunk_words = []

    if not data_segmen:
        raise RuntimeError("Whisper returned an empty transcript; nothing to clip.")
    print(f"      Transcript ready: {len(data_segmen)} subtitle groups.", flush=True)
    return transkrip_lengkap, data_segmen


# =============================================================================
# STAGE 3 — AI ANALYSIS
# =============================================================================

MAX_ATTEMPTS = 10
INITIAL_WAIT_SECONDS = 60
WAIT_INCREMENT_SECONDS = 30
REQUEST_TIMEOUT_MS = 15 * 60 * 1000
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _extract_status_code(exc: Exception):
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    match = re.search(r"\b(408|429|500|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    if _extract_status_code(exc) in RETRYABLE_STATUS_CODES:
        return True
    msg = str(exc).lower()
    keywords = (
        "timeout",
        "temporarily unavailable",
        "deadline",
        "connection reset",
        "connection aborted",
        "service unavailable",
    )
    return any(k in msg for k in keywords)


def _generate_json_with_retry(client, model, fallback_model, contents, config):
    last_exc = None
    status_code = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS}...")
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini returned an empty response.text.")
            return json.loads(text)
        except Exception as exc:
            last_exc = exc
            status_code = _extract_status_code(exc)
            print(f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS} failed | status={status_code} | {exc}")
            if not _is_retryable(exc) or attempt == MAX_ATTEMPTS:
                break
            wait_seconds = INITIAL_WAIT_SECONDS + ((attempt - 1) * WAIT_INCREMENT_SECONDS)
            print(f"[Gemini] Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)

    print(f"[Gemini] Main model ({model}) failed.")
    if fallback_model:
        print(f"[Gemini] Trying the fallback model ({fallback_model}) once...")
        try:
            response = client.models.generate_content(
                model=fallback_model,
                contents=contents,
                config=config,
            )
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini fallback returned an empty response.text.")
            return json.loads(text)
        except Exception as exc_fallback:
            raise RuntimeError(
                "Gemini main and fallback models both failed. "
                f"Main status={status_code}, error={last_exc} | Fallback error={exc_fallback}"
            ) from exc_fallback

    raise RuntimeError(
        f"Gemini failed after {MAX_ATTEMPTS} attempts. Last error: {last_exc}"
    ) from last_exc


def analyze_with_gemini(transkrip_lengkap: str, cfg) -> list[dict]:
    from .providers.gemini import GeminiProvider
    from .providers.schema import build_gemini_schema

    prompt = get_analysis_prompt(
        transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg
    )
    provider = GeminiProvider(
        cfg,
        generate_json=_generate_json_with_retry,
        timeout_ms=REQUEST_TIMEOUT_MS,
    )
    return provider.generate_clips(prompt, build_gemini_schema(TARGET_ACCOUNTS))


def analyze_with_nvidia(transkrip_lengkap: str, cfg) -> list[dict]:
    from .providers.nvidia import NvidiaNimProvider
    from .providers.schema import build_clips_schema

    prompt = get_analysis_prompt(
        transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg
    )
    return NvidiaNimProvider.from_cfg(cfg).generate_clips(
        prompt, build_clips_schema(TARGET_ACCOUNTS)
    )


def analyze_with_vllm(transkrip_lengkap: str, cfg) -> list[dict]:
    from .providers.schema import build_clips_schema
    from .providers.vllm import VllmProvider

    prompt = get_analysis_prompt(
        transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg
    )
    with VllmProvider.from_cfg(cfg) as provider:
        return provider.generate_clips(
            prompt,
            build_clips_schema(TARGET_ACCOUNTS),
            transcript=transkrip_lengkap,
            requested_clips=cfg.jumlah_clip,
            min_duration=MIN_CLIP_DURATION,
            max_duration=MAX_CLIP_DURATION,
        )


def analyze_with_ai(transkrip_lengkap: str, cfg) -> list[dict]:
    """Dispatch analysis; NVIDIA keeps its legacy Gemini fallback."""
    cfg.ai_run_meta = None
    provider = getattr(cfg, "ai_provider", "gemini")
    if provider == "vllm":
        return analyze_with_vllm(transkrip_lengkap, cfg)

    if provider == "nvidia":
        if not getattr(cfg, "api_key_nvidia", ""):
            print("NVIDIA_API_KEY is missing — falling back to Gemini...")
        else:
            try:
                return analyze_with_nvidia(transkrip_lengkap, cfg)
            except Exception as exc:
                print(f"NVIDIA API failed: {exc}. Falling back to Gemini...")

    return analyze_with_gemini(transkrip_lengkap, cfg)

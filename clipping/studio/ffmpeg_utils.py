"""Encoder detection, FFmpeg command assembly and progress-aware execution."""

import os
import re
import shutil
import subprocess

_encoder_cache = {}


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def detect_video_encoder(cfg=None, target_h: int = 1920) -> dict:
    """Prefer NVENC when the local FFmpeg exposes it, otherwise libx264."""
    if "nvenc" in _encoder_cache:
        has_nvenc = _encoder_cache["nvenc"]
    else:
        has_nvenc = False
        if _ffmpeg_available():
            try:
                out = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-encoders"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout
                has_nvenc = "h264_nvenc" in out
            except Exception:
                has_nvenc = False
        _encoder_cache["nvenc"] = has_nvenc

    if has_nvenc:
        return {
            "name": "h264_nvenc",
            "type": "nvenc",
            "cq": getattr(cfg, "video_quality_cq", 23),
            "preset": getattr(cfg, "video_preset", "auto"),
            "bitrate": getattr(cfg, "video_bitrate", "auto"),
        }
    return {
        "name": "libx264",
        "type": "x264",
        "crf": getattr(cfg, "video_quality_crf", 20),
        "preset": getattr(cfg, "video_preset", "auto"),
        "bitrate": getattr(cfg, "video_bitrate", "auto"),
    }


def _bitrate_args(encoder: dict, target_h: int):
    bitrate = str(encoder.get("bitrate") or "auto")
    if bitrate.lower() != "auto":
        return ["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", f"{int(parse_bitrate(bitrate) * 2)}k"]
    # ~0.09 bits per pixel per frame at 30fps, clamped to sane H.264 limits.
    kbps = max(2500, int(target_h * target_h * 9 / 16 * 30 * 0.09 / 1000))
    return ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.4)}k", "-bufsize", f"{kbps * 2}k"]


def parse_bitrate(value: str) -> int:
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM]?)$", str(value).strip())
    if not match:
        return 8000
    amount = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "m":
        return int(amount * 1000)
    if unit == "k":
        return int(amount)
    return int(amount / 1000)


def get_ts_encode_args(encoder: dict, fps: int = 30, target_h: int = 1920):
    """Encoder args for MPEG-TS intermediates (stream-copy concat friendly)."""
    args = ["-c:v", encoder["name"], "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2)]
    if encoder["type"] == "nvenc":
        args += ["-preset", "p5" if encoder.get("preset") in (None, "auto") else encoder["preset"],
                 "-rc", "vbr", "-cq", str(encoder["cq"])]
    else:
        args += ["-preset", "medium" if encoder.get("preset") in (None, "auto") else encoder["preset"],
                 "-crf", str(encoder["crf"])]
    args += _bitrate_args(encoder, target_h)
    args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-f", "mpegts"]
    return args


def get_mp4_encode_args(encoder: dict, fps: int = 30, target_h: int = 1920):
    args = ["-c:v", encoder["name"], "-pix_fmt", "yuv420p", "-r", str(fps)]
    if encoder["type"] == "nvenc":
        args += ["-preset", "p5" if encoder.get("preset") in (None, "auto") else encoder["preset"],
                 "-rc", "vbr", "-cq", str(encoder["cq"])]
    else:
        args += ["-preset", "medium" if encoder.get("preset") in (None, "auto") else encoder["preset"],
                 "-crf", str(encoder["crf"])]
    args += _bitrate_args(encoder, target_h)
    args += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    return args


def get_intermediate_encode_args(encoder: dict, fps: int = 30, target_h: int = 1920):
    """Encode args for the silent visual intermediates (MP4, concat-safe)."""
    return get_mp4_encode_args(encoder, fps=fps, target_h=target_h)


def open_ffmpeg_video_writer(path: str, width: int, height: int, fps: int, encoder: dict):
    """Open an FFmpeg process accepting raw BGR frames; returns the process."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-an",
    ]
    cmd += get_intermediate_encode_args(encoder, fps=fps, target_h=height)
    cmd.append(path)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    return proc


def build_ffmpeg_progress_cmd(cmd: list[str], output_path: str) -> list[str]:
    """Insert -progress so long renders report liveness through stderr."""
    if "-progress" in cmd:
        return cmd
    return cmd[:-1] + ["-progress", "pipe:2", "-nostats", output_path] if cmd else cmd


def run_ffmpeg_with_progress(cmd: list[str], duration: float, label: str = "FFmpeg"):
    """Run FFmpeg, printing sparse progress; returns (returncode, stderr lines)."""
    if not cmd:
        return 1, ["empty command"]
    full = list(cmd)
    if full[-1].endswith((".ts", ".mp4")) and "-progress" not in full:
        full = full[:-1] + ["-progress", "pipe:2", "-nostats", full[-1]]
    print(f"      {label}: running...", flush=True)
    proc = subprocess.Popen(full, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    errors = []
    raw_tail = []
    last_mark = -1
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                raw_tail.append(line)
                del raw_tail[:-60]
            if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                    pct = int(min(100, seconds / max(0.01, duration) * 100))
                    mark = pct // 20
                    if mark != last_mark:
                        print(f"        {label}: {pct}%", flush=True)
                        last_mark = mark
                except ValueError:
                    pass
            elif line and not line.startswith(("frame=", "fps=", "bitrate=", "total_size=",
                                               "out_time=", "dup_frames=", "drop_frames=",
                                               "speed=", "progress=")):
                errors.append(line)
        proc.wait()
    except Exception:
        proc.kill()
        raise
    if proc.returncode != 0:
        if not errors:
            errors = raw_tail[-25:]
        print("FFMPEG_FAILED: " + " ".join(full), flush=True)
        print("FFMPEG_STDERR: " + (" | ".join(raw_tail[-8:]) or "<empty>"), flush=True)
    return proc.returncode, errors[-40:]


def probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return float(out)
    except (ValueError, subprocess.SubprocessError, OSError):
        return 0.0


def probe_dimensions(path: str):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        width, height = out.split("x")[:2]
        return int(width), int(height)
    except (ValueError, subprocess.SubprocessError, OSError):
        return 0, 0


def ensure_ffmpeg() -> None:
    if not _ffmpeg_available():
        raise RuntimeError(
            "FFmpeg is not installed or not on PATH. Install it and restart the backend."
        )


def env_is_set(name: str) -> bool:
    return bool(os.environ.get(name))

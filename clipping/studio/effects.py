"""Generated transitions: cinematic glitch teaser, white flash, hook V2 pieces."""

import os
import subprocess

from .ffmpeg_utils import get_mp4_encode_args
from .utils import _get_render_dims


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-600:])
    return result


def siapkan_glitch_video(
    ratio,
    cfg,
    video_encoder,
    source_h=1080,
    custom_dims=None,
    duration=0.35,
    output_path=None,
):
    """Create a short TV-glitch transition at the target dimensions."""
    width, height = custom_dims or _get_render_dims(cfg, ratio, source_h=source_h)
    path = output_path or os.path.abspath(
        f"glitch_{ratio.replace(':', 'x')}_{width}x{height}.mp4"
    )
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return path

    vf = (
        f"noise=alls=38:allf=t+u,"
        f"rgbashift=rh=8:bh=-8,"
        f"eq=contrast=1.5:brightness=0.06:saturation=0.6,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x07100D:s={width}x{height}:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", vf, "-t", str(duration), "-shortest",
    ] + get_mp4_encode_args(video_encoder, fps=30, target_h=height)
    cmd.append(path)
    _run(cmd)
    return path


def _flash(path, color, duration, width, height, glitch=False):
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
    ]
    if glitch:
        args += ["-vf", "noise=alls=60:allf=t+u,rgbashift=rh=10:bh=-10"]
    args += [
        "-t", str(duration), "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-ar", "48000", "-ac", "2", path,
    ]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def create_white_flash_transition(output_path, duration=0.12, width=1080, height=1920):
    return _flash(output_path, "white", duration, width, height)


def create_glitch_transition(output_path, duration=0.12, width=1080, height=1920):
    return _flash(output_path, "0x0A1512", duration, width, height, glitch=True)


def download_transition_raw(*args, **kwargs):
    """Compatibility shim: transitions are generated locally, not downloaded."""
    return None


def download_all_transitions(*args, **kwargs):
    return []


def get_random_transition(*args, **kwargs):
    return None


def prepare_transition_clip(*args, **kwargs):
    return None


TMP_TRANSITION_POOL = []

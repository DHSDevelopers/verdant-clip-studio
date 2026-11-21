"""Contextual B-roll from Pexels."""

import json
import os
import random
import urllib.parse
import urllib.request


def download_pexels_broll(query: str, ratio: str, output_name: str, api_key: str, min_duration=3):
    """Fetch a stock clip for *query*; returns the local path or None."""
    if not api_key:
        print("      PEXELS_API_KEY is not set; skipping B-roll.")
        return None

    orientation = "portrait" if ratio in {"9:16", "3:4", "4:5"} else "landscape"
    url = (
        "https://api.pexels.com/videos/search?"
        + urllib.parse.urlencode(
            {"query": query, "per_page": 8, "orientation": orientation, "size": "medium"}
        )
    )
    request = urllib.request.Request(url, headers={"Authorization": api_key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"      Pexels search failed for '{query}': {exc}")
        return None

    videos = payload.get("videos") or []
    random.shuffle(videos)
    for video in videos:
        if float(video.get("duration") or 0) < min_duration:
            continue
        files = sorted(
            video.get("video_files") or [],
            key=lambda f: abs((f.get("height") or 0) - 1280),
        )
        link = next((f.get("link") for f in files if f.get("link")), None)
        if not link:
            continue
        try:
            target = os.path.join(os.getcwd(), output_name)
            with urllib.request.urlopen(link, timeout=60) as response, open(target, "wb") as f:
                f.write(response.read())
            return target
        except Exception as exc:
            print(f"      Pexels download failed: {exc}")
    return None


def crop_center_broll(input_path: str, output_path: str, width: int, height: int) -> str:
    import subprocess

    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", input_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height},setsar=1",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", output_path,
        ],
        check=True,
    )
    return output_path

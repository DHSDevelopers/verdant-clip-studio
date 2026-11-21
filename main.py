#!/usr/bin/env python3
"""
Verdant Clip — AI Auto-Clipper & Teaser Generator.

    python main.py --url "https://youtube.com/watch?v=VIDEO_ID"
    python main.py --url URL1 URL2 --clips 3 --ratio 9:16 --cleanup-source
    python main.py --help
"""

import copy
import json
import os
import sys
import time

from clipping.config import _make_url_slug, build_config

VERSION = "1.16.0"

_PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "gdrive": "Google Drive",
}


def _print_banner(cfg, version, url, idx=None, total=None):
    platform = _PLATFORM_LABELS.get(getattr(cfg, "source_platform", "youtube"), "YouTube")
    print("=" * 70)
    if idx is not None and total is not None and total > 1:
        print(f"Verdant Clip v{version} — [{idx}/{total}]")
    else:
        print(f"Verdant Clip v{version}")
    print("=" * 70)
    print(f"   Source      : {platform}")
    print(f"   URL         : {url}")
    print(f"   Clips       : {cfg.jumlah_clip}")
    print(f"   Ratio       : {cfg.pilihan_rasio}")
    print(f"   Font style  : {cfg.gaya_font_aktif}")
    print(f"   Subtitles   : {'OFF' if cfg.no_subs else 'ON'}")
    print(f"   B-Roll      : {'ON' if cfg.use_broll else 'OFF'}")
    print(f"   Hook glitch : {'ON' if cfg.use_hook_glitch else 'OFF'}")
    print(f"   BGM         : {'ON' if cfg.use_auto_bgm else 'OFF'}")
    print(f"   Karaoke     : {'ON' if cfg.use_karaoke_effect else 'OFF'}")
    print(f"   Split-screen: {'ON' if cfg.use_split_screen else 'OFF'}")
    print(f"   Whisper     : {cfg.whisper_model} ({cfg.whisper_device})")
    provider = getattr(cfg, "ai_provider", "gemini")
    print(f"   AI provider : {provider}")
    if getattr(cfg, "watermark_enabled", False):
        print(f"   Watermark   : ON ({cfg.watermark_text or cfg.watermark_image})")
    print("=" * 70)


def _cleanup_source_video(cfg):
    video_path = cfg.file_video_asli
    if os.path.exists(video_path):
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        os.remove(video_path)
        print(f"   Deleted source video ({size_mb:.1f} MB freed)")
    import glob

    for f in glob.glob(video_path.replace(".mp4", ".*.json3")):
        os.remove(f)
    audio_path = video_path.replace(".mp4", "_audio.wav")
    if os.path.exists(audio_path):
        os.remove(audio_path)


def _run_single_url(cfg, url, version, idx=None, total=None):
    from clipping.runner import run_pipeline

    _print_banner(cfg, version, url, idx, total)
    manifest = run_pipeline(cfg)
    if getattr(cfg, "cleanup_source", False):
        print("\nCleaning up the source video...")
        _cleanup_source_video(cfg)
    return manifest


def main():
    cfg = build_config(sys.argv[1:])

    from clipping.providers.validation import validate_analysis_config

    try:
        validate_analysis_config(cfg, check_cache=False)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    url_list = getattr(
        cfg, "url_list", [cfg.url_youtube] if isinstance(cfg.url_youtube, str) else cfg.url_youtube
    )
    if len(url_list) == 1:
        _run_single_url(cfg, url_list[0], VERSION)
        print("\nDone. All clips were rendered.")
        return

    base_outputs_dir = cfg.outputs_dir
    total = len(url_list)
    print("=" * 70)
    print(f"Verdant Clip v{VERSION} — Batch Mode")
    print(f"   Total URLs : {total}")
    for i, url in enumerate(url_list):
        print(f"   [{i + 1}] {url}")
    print("=" * 70)

    results, errors = [], []
    batch_start = time.time()
    global_whisper = None
    try:
        from faster_whisper import WhisperModel

        print(f"Pre-loading Whisper '{cfg.whisper_model}' for batch processing...")
        global_whisper = WhisperModel(
            cfg.whisper_model, device=cfg.whisper_device, compute_type=cfg.whisper_compute_type
        )
    except Exception as exc:
        print(f"Whisper pre-load skipped: {exc}")

    for idx, url in enumerate(url_list):
        started = time.time()
        url_cfg = copy.copy(cfg)
        url_cfg.url_youtube = url
        url_cfg.url_list = [url]
        slug = _make_url_slug(url, idx)
        url_cfg.outputs_dir = os.path.join(base_outputs_dir, slug)
        os.makedirs(url_cfg.outputs_dir, exist_ok=True)
        url_cfg.file_video_asli = os.path.join(url_cfg.outputs_dir, "video_asli.mp4")

        print(f"\n[{idx + 1}/{total}] Processing: {url}")
        try:
            from clipping.runner import run_pipeline

            _print_banner(url_cfg, VERSION, url, idx + 1, total)
            manifest = run_pipeline(url_cfg, whisper_model_instance=global_whisper)
            if getattr(url_cfg, "cleanup_source", False):
                _cleanup_source_video(url_cfg)
            elapsed = time.time() - started
            results.append(
                {
                    "index": idx + 1,
                    "url": url,
                    "slug": slug,
                    "output_dir": url_cfg.outputs_dir,
                    "status": "success",
                    "clips_rendered": len(manifest or []),
                    "duration_seconds": round(elapsed, 1),
                    "manifest": manifest,
                }
            )
        except Exception as exc:
            elapsed = time.time() - started
            errors.append({"index": idx + 1, "url": url, "error": str(exc)})
            results.append(
                {
                    "index": idx + 1,
                    "url": url,
                    "slug": slug,
                    "output_dir": url_cfg.outputs_dir,
                    "status": "failed",
                    "error": str(exc),
                    "duration_seconds": round(elapsed, 1),
                    "manifest": None,
                }
            )
            print(f"Failed: {exc}")

    total_elapsed = time.time() - batch_start
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    batch_path = os.path.join(base_outputs_dir, "batch_manifest.json")
    with open(batch_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "batch_mode": True,
                "total_urls": total,
                "success": success,
                "failed": failed,
                "total_duration_seconds": round(total_elapsed, 1),
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print("=" * 70)
    print(f"Batch complete: {success} succeeded, {failed} failed in {total_elapsed:.0f}s")
    print(f"Manifest: {batch_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()

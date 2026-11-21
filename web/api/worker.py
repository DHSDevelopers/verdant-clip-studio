"""Background worker wrapping the clipping pipeline with progress reporting."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from . import store
from .config_adapter import build_config_from_payload
from .models import ClipDetail, JobStatus

# The renderer uses shared FFmpeg scratch state; jobs stay serial.
MAX_CONCURRENT_JOBS = 1
if os.environ.get("MAX_CONCURRENT_JOBS", "1") != "1":
    logging.getLogger(__name__).warning(
        "API jobs run one at a time because the renderer shares temporary files."
    )
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)
_tasks: dict[str, asyncio.Task] = {}
_running_jobs: set[str] = set()
_settings_env: dict[str, str] = {}

logger = logging.getLogger(__name__)


def set_settings_env(env: dict[str, str]) -> None:
    _settings_env.update(env)


def get_settings_env() -> dict[str, str]:
    return dict(_settings_env)


class JobCancelled(Exception):
    pass


def _check_cancelled(job_id: str) -> None:
    if store.is_cancel_requested(job_id):
        raise JobCancelled()


def is_job_active(job_id: str) -> bool:
    task = _tasks.get(job_id)
    return job_id in _running_jobs or (task is not None and not task.done())


def cancel_job(job_id: str) -> bool:
    if not store.request_cancel(job_id):
        return False
    if job_id not in _running_jobs:
        task = _tasks.get(job_id)
        if task is not None:
            task.cancel()
        store.finish_job(job_id)
    return True


async def cancel_all_jobs() -> None:
    for job_id in list(_tasks):
        cancel_job(job_id)
    await asyncio.sleep(0)


def _clips_from_manifest(job_id: str, manifest: list[dict]) -> list[ClipDetail]:
    clips = []
    for entry in manifest:
        if entry.get("status") != "success" or not entry.get("video_exists", False):
            continue
        try:
            filename = os.path.basename(
                entry.get("output_file") or entry.get("video_path") or ""
            )
            if not filename:
                continue
            thumb = ""
            thumb_path = entry.get("thumbnail_path")
            if thumb_path and os.path.exists(thumb_path):
                thumb = (
                    f"/api/outputs/{quote(job_id, safe='')}/"
                    f"{quote(os.path.basename(thumb_path), safe='')}"
                )
            clips.append(
                ClipDetail(
                    rank=entry.get("rank", 0),
                    viral_score=entry.get("viral_score"),
                    title=entry.get("title_indonesia", ""),
                    title_en=entry.get("title_inggris", ""),
                    filename=filename,
                    duration=entry.get("duration"),
                    start_time=entry.get("start_time"),
                    end_time=entry.get("end_time"),
                    download_url=f"/api/outputs/{quote(job_id, safe='')}/{quote(filename, safe='')}",
                    thumbnail_url=thumb or None,
                    metadata=entry,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Invalid renderer metadata (%s)", type(exc).__name__)
    return clips


def _validate_analysis_config(cfg) -> None:
    from clipping.providers.validation import validate_analysis_config

    validate_analysis_config(cfg, probe=False)


def _run_pipeline_sync(job_id: str, payload: dict) -> None:
    render_manifest: list[dict] = []
    try:
        _check_cancelled(job_id)
        cfg = build_config_from_payload(payload, job_id, env_overrides=_settings_env)
        _validate_analysis_config(cfg)

        # ---------------------------------------------------------- 1 download
        store.set_status(job_id, JobStatus.DOWNLOADING)
        store.update_progress(
            job_id, "download", 1, 7,
            "Acquiring the source video..." if not payload.get("upload_filename")
            else "Using the uploaded source video.",
            5.0,
        )

        from clipping import engine

        source_platform = getattr(cfg, "source_platform", "youtube")
        if payload.get("upload_filename"):
            if not os.path.exists(cfg.file_video_asli):
                raise ValueError("Uploaded video was not found.")
            store.update_progress(job_id, "download", 1, 7, "Uploaded file ready.", 14.0)
        elif not cfg.url_youtube:
            if os.path.exists(cfg.file_video_asli):
                store.update_progress(
                    job_id, "download", 1, 7, "Bypass download: reusing the previous video.", 14.0
                )
            else:
                raise ValueError(
                    "The original video for this job no longer exists. Create a new job from the URL."
                )
        else:
            engine.download_video(
                cfg.url_youtube,
                cfg.file_video_asli,
                getattr(cfg, "use_dlp_subs", False),
                getattr(cfg, "download_source_height", "max"),
                source_platform=source_platform,
                yt_cookies=getattr(cfg, "yt_cookies", None),
            )
            store.update_progress(job_id, "download", 1, 7, "Source video downloaded.", 14.0)

        _check_cancelled(job_id)

        # ------------------------------------------------------- 2 transcribe
        store.set_status(job_id, JobStatus.TRANSCRIBING)
        store.update_progress(job_id, "transcribe", 2, 7, "Starting transcription...", 15.0)

        transkrip_lengkap = ""
        data_segmen = []
        json3_files = glob.glob(str(Path(cfg.file_video_asli).with_suffix("")) + ".*.json3")
        file_json3 = json3_files[0] if json3_files else None
        if (
            source_platform == "youtube"
            and getattr(cfg, "use_dlp_subs", False)
            and file_json3
            and os.path.exists(file_json3)
        ):
            transkrip_lengkap, data_segmen = engine.parse_youtube_json3_subs(
                file_json3, max_words_per_subtitle=cfg.max_kata_per_subtitle
            )

        if not transkrip_lengkap or not data_segmen:
            transkrip_lengkap, data_segmen = engine.transcribe_video(
                cfg.file_video_asli,
                max_words_per_subtitle=cfg.max_kata_per_subtitle,
                model_size=cfg.whisper_model,
                device=cfg.whisper_device,
                compute_type=cfg.whisper_compute_type,
            )
        store.update_progress(
            job_id, "transcribe", 2, 7,
            f"Transcript ready ({len(data_segmen)} caption groups).", 35.0,
        )

        _check_cancelled(job_id)

        # ---------------------------------------------------------- 3 analyze
        store.set_status(job_id, JobStatus.ANALYZING)
        store.update_progress(
            job_id, "analyze", 3, 7,
            "Ranking hooks and scoring viral moments. Provider retries may take a few minutes.",
            36.0,
        )
        gemini_output_path = os.path.join(cfg.outputs_dir, "gemini_response.json")
        from clipping.providers.metadata import save_run_metadata

        if getattr(cfg, "load_gemini_json", False) and os.path.exists(gemini_output_path):
            with open(gemini_output_path, "r", encoding="utf-8") as f:
                hasil_json = json.load(f)
            save_run_metadata(cfg, cached=True)
        else:
            hasil_json = engine.analyze_with_ai(transkrip_lengkap, cfg)
            with open(gemini_output_path, "w", encoding="utf-8") as f:
                json.dump(hasil_json, f, indent=4, ensure_ascii=False)
            save_run_metadata(cfg)
        store.update_progress(
            job_id, "analyze", 3, 7, f"AI selected {len(hasil_json)} clips.", 50.0
        )

        _check_cancelled(job_id)

        # --------------------------------------------------------- 4 metadata
        from clipping import metadata

        hasil_json = metadata.normalize_and_validate(hasil_json)
        if not hasil_json:
            raise ValueError("The AI returned no valid clips to render.")
        metadata.save_metadata_preview(
            hasil_json, path=os.path.join(cfg.outputs_dir, "metadata_preview.json")
        )
        store.update_progress(job_id, "metadata", 4, 7, "Metadata normalized.", 55.0)

        _check_cancelled(job_id)

        # ------------------------------------------------------- 5 diarization
        diarization_data = None
        from clipping import diarization as diarization_mod
        from clipping import studio

        if (
            (getattr(cfg, "use_split_screen", False) and cfg.split_trigger == "diarization")
            or getattr(cfg, "use_camera_switch", False)
        ) and studio._is_vertical_ratio(cfg.pilihan_rasio):
            try:
                store.update_progress(
                    job_id, "diarization", 5, 7, "Running speaker diarization...", 56.0
                )
                audio_path = str(Path(cfg.outputs_dir) / "diarization_audio.wav")
                diarization_mod.extract_audio(cfg.file_video_asli, audio_path)
                num_speakers_arg = getattr(cfg, "diarization_num_speakers", 2)
                min_spk = max_spk = None
                if str(num_speakers_arg).lower() == "auto":
                    max_faces = studio.estimate_speaker_count_from_video(cfg.file_video_asli, cfg)
                    min_spk = max(1, max_faces)
                    max_spk = min_spk + 2
                diarization_data = diarization_mod.run_diarization(
                    audio_path,
                    hf_token=cfg.hf_token,
                    num_speakers=num_speakers_arg,
                    min_speakers=min_spk,
                    max_speakers=max_spk,
                )
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception as exc:
                store.update_progress(
                    job_id, "diarization", 5, 7,
                    f"Diarization unavailable ({exc}). Continuing with standard framing.", 58.0,
                )
                diarization_data = None

        _check_cancelled(job_id)

        # ------------------------------------------------------ 6 render prep
        store.set_status(job_id, JobStatus.RENDERING)
        store.update_progress(
            job_id, "render", 6, 7, "Preparing smart framing and encoder...", 60.0
        )
        os.environ["OSC_VIDEO_SCALE_ALGO"] = str(getattr(cfg, "video_scale_algo", "lanczos"))

        import cv2

        cap = cv2.VideoCapture(cfg.file_video_asli)
        if not cap.isOpened():
            raise ValueError("OpenCV cannot read the downloaded source video.")
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        _w, target_h = studio._get_render_dims(cfg, cfg.pilihan_rasio, source_h=src_h)
        video_encoder = studio.detect_video_encoder(cfg, target_h=target_h)

        file_glitch_ts = None
        if cfg.use_hook_glitch:
            file_glitch_ts = studio.siapkan_glitch_video(
                cfg.pilihan_rasio, cfg, video_encoder, source_h=src_h
            )

        # ------------------------------------------------------- 7 render loop
        from clipping import hook_manager

        total_clips = len(hasil_json)
        custom_hook_path = None
        if getattr(cfg, "hook_source", None):
            custom_hook_path = hook_manager.download_custom_hook(cfg)

        for idx, klip in enumerate(sorted(hasil_json, key=lambda x: x["rank"])):
            _check_cancelled(job_id)
            clip_num = idx + 1
            store.update_progress(
                job_id, "render", 6, 7,
                f"Rendering clip {clip_num}/{total_clips}: {klip.get('title_inggris', '')[:60]}",
                60.0 + (35.0 * clip_num / total_clips),
            )
            if custom_hook_path:
                klip["custom_hook_info"] = {"file_path": custom_hook_path}
            result = studio.proses_klip(
                klip["rank"], klip, cfg.pilihan_rasio, file_glitch_ts,
                data_segmen, cfg, video_encoder, diarization_data=diarization_data,
            )
            if not isinstance(result, dict):
                result = {"rank": klip["rank"], "status": "failed",
                          "error": "Renderer returned no result"}
            render_manifest.append(result)
            manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(render_manifest, f, ensure_ascii=False, indent=2)
            _check_cancelled(job_id)

        manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(render_manifest, f, ensure_ascii=False, indent=2)

        clips = _clips_from_manifest(job_id, render_manifest)
        failed = total_clips - len(clips)
        error = (
            f"{failed}/{total_clips} clips failed to render. See render_manifest.json."
            if failed else None
        )
        store.finish_job(job_id, clips=clips, error=error)

    except JobCancelled:
        store.finish_job(job_id, clips=_clips_from_manifest(job_id, render_manifest))
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        store.finish_job(
            job_id,
            clips=_clips_from_manifest(job_id, render_manifest),
            error=f"{type(exc).__name__}: {exc}",
        )


async def submit_job(job_id: str, payload: dict) -> None:
    if is_job_active(job_id):
        raise ValueError("Job is already running")

    async def _run():
        try:
            async with _semaphore:
                _running_jobs.add(job_id)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(_executor, _run_pipeline_sync, job_id, payload)
        except Exception as exc:
            logger.error("Job dispatch failed (%s)", type(exc).__name__)
            raise
        finally:
            _running_jobs.discard(job_id)

    task = asyncio.create_task(_run())
    _tasks[job_id] = task

    def _forget(done_task):
        if _tasks.get(job_id) is done_task:
            _tasks.pop(job_id, None)

    task.add_done_callback(_forget)

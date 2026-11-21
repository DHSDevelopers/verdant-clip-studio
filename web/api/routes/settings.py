"""Settings, health, readiness and UI metadata endpoints."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import store as job_store
from .. import worker
from ..models import SettingsRequest, SettingsResponse, SystemHealthResponse
from ..readiness import get_readiness
from clipping.config import DAFTAR_FONT
from clipping.presets import PRESETS

router = APIRouter(tags=["settings"])


@lru_cache(maxsize=1)
def _check_gpu() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _check_ffmpeg() -> bool:
    try:
        return subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5
        ).returncode == 0
    except Exception:
        return False


@router.get("/api/settings")
async def get_settings() -> SettingsResponse:
    env = worker.get_settings_env()
    from clipping.providers.config import DEFAULT_LOCAL_MAX_TOKENS, DEFAULT_VLLM_MODEL

    vllm_model = env.get("VLLM_MODEL", os.environ.get("VLLM_MODEL", DEFAULT_VLLM_MODEL))
    try:
        local_max_tokens = int(
            env.get("VLLM_MAX_TOKENS", os.environ.get("VLLM_MAX_TOKENS", DEFAULT_LOCAL_MAX_TOKENS))
        )
        if not 1 <= local_max_tokens <= 131072:
            local_max_tokens = DEFAULT_LOCAL_MAX_TOKENS
    except (TypeError, ValueError):
        local_max_tokens = DEFAULT_LOCAL_MAX_TOKENS

    return SettingsResponse(
        google_api_key_set=bool(env.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))),
        pexels_api_key_set=bool(env.get("PEXELS_API_KEY", os.environ.get("PEXELS_API_KEY", ""))),
        hf_token_set=bool(env.get("HF_TOKEN", os.environ.get("HF_TOKEN", ""))),
        nvidia_api_key_set=bool(env.get("NVIDIA_API_KEY", os.environ.get("NVIDIA_API_KEY", ""))),
        vllm_api_key_set=bool(env.get("VLLM_API_KEY", os.environ.get("VLLM_API_KEY", ""))),
        vllm_model=vllm_model,
        local_max_tokens=local_max_tokens,
        default_clips=int(env.get("DEFAULT_CLIPS", "7")),
        default_ratio=env.get("DEFAULT_RATIO", "9:16"),
        default_font_style=env.get("DEFAULT_FONT_STYLE", "HORMOZI"),
        default_whisper_model=env.get("DEFAULT_WHISPER_MODEL", "large-v3"),
        default_whisper_device=env.get("DEFAULT_WHISPER_DEVICE", "cuda"),
        default_ai_provider=env.get("DEFAULT_AI_PROVIDER", "gemini"),
        gpu_available=await asyncio.to_thread(_check_gpu),
    )


@router.put("/api/settings")
async def update_settings(req: SettingsRequest) -> SettingsResponse:
    updates = {}
    if req.google_api_key is not None:
        updates["GOOGLE_API_KEY"] = req.google_api_key
    if req.pexels_api_key is not None:
        updates["PEXELS_API_KEY"] = req.pexels_api_key
    if req.hf_token is not None:
        updates["HF_TOKEN"] = req.hf_token
    if req.nvidia_api_key is not None:
        updates["NVIDIA_API_KEY"] = req.nvidia_api_key
    if req.default_clips is not None:
        updates["DEFAULT_CLIPS"] = str(req.default_clips)
    if req.default_ratio is not None:
        updates["DEFAULT_RATIO"] = req.default_ratio.value
    if req.default_font_style is not None:
        updates["DEFAULT_FONT_STYLE"] = req.default_font_style.value
    if req.default_whisper_model is not None:
        updates["DEFAULT_WHISPER_MODEL"] = req.default_whisper_model
    if req.default_whisper_device is not None:
        updates["DEFAULT_WHISPER_DEVICE"] = req.default_whisper_device.value
    if req.default_ai_provider is not None:
        updates["DEFAULT_AI_PROVIDER"] = req.default_ai_provider.value

    worker.set_settings_env(updates)
    return await get_settings()


@router.get("/api/health")
async def health_check() -> SystemHealthResponse:
    gpu_available, ffmpeg_available = await asyncio.gather(
        asyncio.to_thread(_check_gpu), asyncio.to_thread(_check_ffmpeg)
    )
    return SystemHealthResponse(
        status="ok",
        version="1.16.0",
        gpu_available=gpu_available,
        ffmpeg_available=ffmpeg_available,
        jobs_running=job_store.get_running_count(),
        jobs_queued=job_store.get_queued_count(),
    )


@router.get("/api/ready")
async def readiness_check() -> JSONResponse:
    result = await asyncio.to_thread(get_readiness)
    return JSONResponse(result, status_code=200 if result["ready"] else 503)


@router.get("/api/meta")
async def meta() -> dict:
    """Everything the UI needs to render controls and presets."""
    return {
        "version": "1.16.0",
        "scaffold": "verdent-studio",
        "ratios": ["9:16", "16:9", "1:1", "3:4", "4:5"],
        "font_styles": [
            {"id": key, "label": value["utama"]["nama"]} for key, value in DAFTAR_FONT.items()
        ],
        "providers": ["gemini", "nvidia", "vllm"],
        "sources": ["youtube", "tiktok", "instagram", "gdrive"],
        "presets": PRESETS,
        "naming_tokens": ["{rank}", "{slug}", "{date}"],
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "readiness": get_readiness(),
    }

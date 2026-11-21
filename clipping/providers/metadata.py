"""Provider provenance sidecar (no transcript text is ever written)."""

import hashlib
import json
import os
from datetime import datetime, timezone


def save_run_metadata(cfg, cached: bool = False) -> None:
    meta = getattr(cfg, "ai_run_meta", None) or {}
    payload = {
        "provider": getattr(cfg, "ai_provider", "gemini"),
        "model": (
            getattr(cfg, "vllm_model", None)
            if getattr(cfg, "ai_provider", "") == "vllm"
            else getattr(cfg, "nvidia_model", None)
            if getattr(cfg, "ai_provider", "") == "nvidia"
            else getattr(cfg, "gemini_model", None)
        ),
        "cached": bool(cached),
        "attempts": meta.get("attempts"),
        "usage": meta.get("usage"),
        "duration_seconds": meta.get("duration_seconds"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "prompt_sha256": meta.get("prompt_sha256"),
    }
    path = os.path.join(cfg.outputs_dir, "ai_run_meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
